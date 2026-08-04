"""Tests de la búsqueda en vivo con persistencia (`app/services/live_search.py`).

Sin red: se sustituye `_fetch_one_source`, que es la única función del módulo que hace
HTTP. Lo que se prueba es el contrato del servicio — qué guarda, qué no vuelve a pedir,
y que una tienda caída no rompa la búsqueda.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.adapters.types import NormalizedListingInput, ProductHint
from app.enums import ItemCondition, SourceKind, SourceStatus, WarrantyType
from app.models.listing import Listing
from app.models.retailer_source import RetailerSource
from app.services import live_search


@pytest.fixture(autouse=True)
def _clear_cooldown():
    """El cooldown vive en memoria del proceso: se limpia entre tests."""
    live_search._last_fetch.clear()
    yield
    live_search._last_fetch.clear()


def _active_source(db: Session, slug: str) -> RetailerSource:
    source = RetailerSource(
        slug=slug,
        display_name=slug.capitalize(),
        kind=SourceKind.VTEX,
        status=SourceStatus.ACTIVE,
        config_json={},
    )
    db.add(source)
    db.flush()
    return source


def _normalized(slug: str, external_id: str, title: str, price: str) -> NormalizedListingInput:
    return NormalizedListingInput(
        source_slug=slug,
        external_id=external_id,
        title=title,
        permalink=f"https://{slug}.test/{external_id}",
        condition=ItemCondition.NEW,
        price=Decimal(price),
        currency="ARS",
        warranty_type=WarrantyType.UNKNOWN,
        product_hint=ProductHint(),
        fetched_at=datetime.now(timezone.utc),
    )


def _fake_fetch(payload: dict[str, list[NormalizedListingInput]], failing: set[str] | None = None):
    """Reemplaza la fase de red: devuelve lo que diga `payload`, por slug."""
    failing = failing or set()

    def _fake(source_id, slug, kind, config, term, per_source):
        if slug in failing:
            return source_id, slug, [], "la tienda no responde"
        return source_id, slug, payload.get(slug, []), None

    return _fake


def test_fetch_live_persists_and_groups(db_session: Session, monkeypatch) -> None:
    a = _active_source(db_session, "cetrogar")
    b = _active_source(db_session, "naldo")
    db_session.commit()

    monkeypatch.setattr(
        live_search,
        "_fetch_one_source",
        _fake_fetch(
            {
                "cetrogar": [_normalized("cetrogar", "C1", "Pava Eléctrica Codini P18MAN Inox", "21999")],
                "naldo": [_normalized("naldo", "N1", "Pava Electrica Codini P18MAN 1.7L", "25999")],
            }
        ),
    )

    result = live_search.fetch_live(db_session, "pava electrica")

    assert result.inserted == 2
    assert sorted(result.sources_ok) == ["cetrogar", "naldo"]
    listings = db_session.scalars(select(Listing)).all()
    assert len(listings) == 2
    # Lo traído en vivo tiene que quedar agrupado: sin producto asignado no aparece en
    # `/search`, que hace INNER JOIN contra `product`.
    assert all(listing.product_id is not None for listing in listings)
    assert len({listing.product_id for listing in listings}) == 1


def test_second_call_updates_instead_of_duplicating(db_session: Session, monkeypatch) -> None:
    """Misma clave natural: la segunda corrida actualiza, no inserta de nuevo."""
    _active_source(db_session, "cetrogar")
    db_session.commit()

    monkeypatch.setattr(
        live_search,
        "_fetch_one_source",
        _fake_fetch({"cetrogar": [_normalized("cetrogar", "C1", "Pava Eléctrica Codini", "21999")]}),
    )

    live_search.fetch_live(db_session, "pava")
    segunda = live_search.fetch_live(db_session, "pava", force=True)

    assert segunda.inserted == 0
    assert segunda.updated == 1
    assert db_session.scalar(select(func.count(Listing.id))) == 1


def test_cooldown_prevents_hammering_the_stores(db_session: Session, monkeypatch) -> None:
    """Un F5 sobre la misma búsqueda no puede disparar tráfico a las tiendas de nuevo."""
    _active_source(db_session, "cetrogar")
    db_session.commit()

    llamadas = {"n": 0}

    def _contando(source_id, slug, kind, config, term, per_source):
        llamadas["n"] += 1
        return source_id, slug, [], None

    monkeypatch.setattr(live_search, "_fetch_one_source", _contando)

    live_search.fetch_live(db_session, "heladera")
    segunda = live_search.fetch_live(db_session, "heladera")

    assert llamadas["n"] == 1
    assert segunda.skipped_by_cooldown is True


def test_a_failing_store_does_not_break_the_search(db_session: Session, monkeypatch) -> None:
    _active_source(db_session, "cetrogar")
    _active_source(db_session, "naldo")
    db_session.commit()

    monkeypatch.setattr(
        live_search,
        "_fetch_one_source",
        _fake_fetch(
            {"naldo": [_normalized("naldo", "N1", "Lavarropas Drean Next 8kg", "700000")]},
            failing={"cetrogar"},
        ),
    )

    result = live_search.fetch_live(db_session, "lavarropas")

    assert result.sources_ok == ["naldo"]
    assert result.sources_failed == ["cetrogar"]
    assert result.inserted == 1


def test_inactive_sources_are_not_queried(db_session: Session, monkeypatch) -> None:
    """Una fuente pausada (ML sin token, o bloqueada) no se consulta."""
    pausada = _active_source(db_session, "mercadolibre")
    pausada.status = SourceStatus.BLOCKED_TOS_REVIEW
    db_session.commit()

    consultadas: list[str] = []

    def _registrando(source_id, slug, kind, config, term, per_source):
        consultadas.append(slug)
        return source_id, slug, [], None

    monkeypatch.setattr(live_search, "_fetch_one_source", _registrando)

    live_search.fetch_live(db_session, "iphone")

    assert consultadas == []


def test_search_endpoint_triggers_live_fetch_when_db_is_empty(
    db_session: Session, client: TestClient, monkeypatch
) -> None:
    """El circuito completo: buscar algo que no está -> se trae -> se devuelve."""
    _active_source(db_session, "cetrogar")
    db_session.commit()

    monkeypatch.setattr(
        live_search,
        "_fetch_one_source",
        _fake_fetch(
            {"cetrogar": [_normalized("cetrogar", "C9", "Cafetera Express Philips 3200", "450000")]}
        ),
    )

    body = client.get("/search", params={"q": "cafetera express"}).json()

    assert body["total"] == 1
    assert body["items"][0]["canonical_title"].startswith("Cafetera Express")


def test_search_endpoint_skips_live_when_db_already_has_enough(
    db_session: Session, client: TestClient, seeded_db: Session, monkeypatch
) -> None:
    """`live=false` desactiva la consulta a las tiendas explícitamente."""
    llamadas = {"n": 0}

    def _contando(source_id, slug, kind, config, term, per_source):
        llamadas["n"] += 1
        return source_id, slug, [], None

    monkeypatch.setattr(live_search, "_fetch_one_source", _contando)

    client.get("/search", params={"q": "iphone", "live": "false"})

    assert llamadas["n"] == 0

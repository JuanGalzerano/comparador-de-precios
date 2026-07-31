"""Tests del worker de ingesta (`app/workers/ingest.py`).

Mockea HTTP con `respx` (mismo patron que `tests/test_mercadolibre_adapter.py`) y usa
SQLite en memoria via los fixtures `db_engine`/`db_session` ya definidos en
`tests/conftest.py` (no se redefinen aca, pytest los resuelve automaticamente para
cualquier test de este directorio).

Todos los `SearchQuery` de estos tests usan `enrich=False`: lo que se ejercita aca es el
upsert/price_history/campos de `retailer_source`, no el enrichment de `MercadoLibreAdapter`
(ya cubierto en `test_mercadolibre_adapter.py`). Con `enrich=False` alcanza con mockear
`/sites/MLA/search`, sin `/users/:id` ni `/reviews/item/:id`.
"""

from __future__ import annotations

from decimal import Decimal

import httpx
import respx

from app.adapters.types import SearchQuery
from app.enums import SourceKind, SourceStatus
from app.models.listing import Listing
from app.models.price_history import PriceHistory
from app.models.retailer_source import RetailerSource
from app.workers.ingest import ingest_source

BASE_URL = "https://api.mercadolibre.com"


def _make_source(db_session, slug: str = "mercadolibre") -> RetailerSource:
    source = RetailerSource(slug=slug, kind=SourceKind.API, status=SourceStatus.ACTIVE)
    db_session.add(source)
    db_session.commit()
    db_session.refresh(source)
    return source


def _item(item_id: str, price: int, **overrides) -> dict:
    item = {
        "id": item_id,
        "title": f"Producto {item_id}",
        "permalink": f"https://articulo.mercadolibre.com.ar/{item_id}",
        "condition": "new",
        "price": price,
        "currency_id": "ARS",
        "official_store_id": None,
        "shipping": {"free_shipping": True},
        "installments": {"quantity": 12, "amount": price / 12, "rate": 0},
        "seller": {"id": 999, "nickname": "VendedorTest"},
        "attributes": [],
    }
    item.update(overrides)
    return item


def _search_response(items: list[dict]) -> httpx.Response:
    return httpx.Response(
        200,
        json={"results": items, "paging": {"total": len(items), "offset": 0, "limit": 50}},
    )


# ---------------------------------------------------------------------------
# Primera corrida: insert + price_history por cada listing
# ---------------------------------------------------------------------------


@respx.mock
def test_first_run_inserts_listings_and_creates_price_history(db_session):
    source = _make_source(db_session)
    respx.get(f"{BASE_URL}/sites/MLA/search").mock(
        return_value=_search_response(
            [_item("MLA-1", 100000), _item("MLA-2", 200000)]
        )
    )

    result = ingest_source(
        db_session, source.slug, SearchQuery(term="iphone", enrich=False)
    )

    assert result.inserted == 2
    assert result.updated == 0
    assert result.price_points_added == 2
    assert result.item_errors == []

    listings = db_session.query(Listing).order_by(Listing.external_id).all()
    assert [l.external_id for l in listings] == ["MLA-1", "MLA-2"]
    assert listings[0].price == Decimal("100000")
    assert listings[0].product_id is None  # matching es un paso aparte

    price_points = db_session.query(PriceHistory).all()
    assert len(price_points) == 2

    db_session.refresh(source)
    assert source.last_run_at is not None
    assert source.last_success_at is not None
    assert source.last_error is None


# ---------------------------------------------------------------------------
# Segunda corrida, mismo precio: se actualiza la listing pero NO se duplica historial
# ---------------------------------------------------------------------------


@respx.mock
def test_second_run_same_price_does_not_duplicate_price_history(db_session):
    source = _make_source(db_session)
    respx.get(f"{BASE_URL}/sites/MLA/search").mock(
        return_value=_search_response(
            [_item("MLA-1", 100000), _item("MLA-2", 200000)]
        )
    )

    ingest_source(db_session, source.slug, SearchQuery(term="iphone", enrich=False))
    result2 = ingest_source(
        db_session, source.slug, SearchQuery(term="iphone", enrich=False)
    )

    assert result2.inserted == 0
    assert result2.updated == 2
    assert result2.price_points_added == 0

    assert db_session.query(Listing).count() == 2
    assert db_session.query(PriceHistory).count() == 2  # sigue en 2, no 4


# ---------------------------------------------------------------------------
# Segunda corrida, precio distinto: actualiza listing.price Y agrega price_history
# ---------------------------------------------------------------------------


@respx.mock
def test_second_run_with_different_price_updates_and_adds_price_point(db_session):
    source = _make_source(db_session)
    route = respx.get(f"{BASE_URL}/sites/MLA/search")
    route.side_effect = [
        _search_response([_item("MLA-1", 100000), _item("MLA-2", 200000)]),
        _search_response([_item("MLA-1", 89990), _item("MLA-2", 200000)]),
    ]

    ingest_source(db_session, source.slug, SearchQuery(term="iphone", enrich=False))
    result2 = ingest_source(
        db_session, source.slug, SearchQuery(term="iphone", enrich=False)
    )

    assert result2.inserted == 0
    assert result2.updated == 2
    # Solo MLA-1 cambio de precio: un solo punto nuevo, no dos.
    assert result2.price_points_added == 1

    listing_1 = (
        db_session.query(Listing).filter_by(external_id="MLA-1").one()
    )
    assert listing_1.price == Decimal("89990")
    assert listing_1.final_price == Decimal("89990")  # shipping_cost = 0 (free_shipping)

    # Historial total: 2 (primera corrida) + 1 (el cambio de MLA-1) = 3.
    assert db_session.query(PriceHistory).count() == 3
    history_for_1 = (
        db_session.query(PriceHistory)
        .filter_by(listing_id=listing_1.id)
        .order_by(PriceHistory.captured_at)
        .all()
    )
    assert [h.price for h in history_for_1] == [Decimal("100000"), Decimal("89990")]


# ---------------------------------------------------------------------------
# Item malformado (sin price) no rompe el resto del batch
# ---------------------------------------------------------------------------


@respx.mock
def test_malformed_item_does_not_break_the_rest_of_the_batch(db_session):
    source = _make_source(db_session)
    good_item = _item("MLA-1", 100000)
    bad_item = _item("MLA-2", 200000)
    del bad_item["price"]  # dispara NormalizationError en adapter.normalize()

    respx.get(f"{BASE_URL}/sites/MLA/search").mock(
        return_value=_search_response([good_item, bad_item])
    )

    result = ingest_source(
        db_session, source.slug, SearchQuery(term="iphone", enrich=False)
    )

    assert result.inserted == 1
    assert result.updated == 0
    assert len(result.item_errors) == 1
    assert "MLA-2" in result.item_errors[0]

    listings = db_session.query(Listing).all()
    assert len(listings) == 1
    assert listings[0].external_id == "MLA-1"

    db_session.refresh(source)
    # La corrida en si NO fallo (el adapter no levanto una excepcion de nivel-corrida):
    # last_success_at se actualiza igual, pero last_error deja constancia del item roto.
    assert source.last_run_at is not None
    assert source.last_success_at is not None
    assert source.last_error is not None
    assert "1 item" in source.last_error


# ---------------------------------------------------------------------------
# retailer_source.last_run_at / last_success_at / last_error: corrida exitosa
# ---------------------------------------------------------------------------


@respx.mock
def test_successful_run_updates_source_bookkeeping_and_clears_last_error(db_session):
    source = _make_source(db_session)
    source.last_error = "un error viejo de una corrida anterior"
    db_session.add(source)
    db_session.commit()

    respx.get(f"{BASE_URL}/sites/MLA/search").mock(
        return_value=_search_response([_item("MLA-1", 100000)])
    )

    before = source.last_run_at
    ingest_source(db_session, source.slug, SearchQuery(term="iphone", enrich=False))

    db_session.refresh(source)
    assert source.last_run_at != before
    assert source.last_success_at is not None
    assert source.last_error is None  # se limpia el error viejo


# ---------------------------------------------------------------------------
# Fuente inexistente: error de configuracion explicito, no un 500 generico
# ---------------------------------------------------------------------------


def test_ingest_unknown_source_slug_raises_source_not_configured(db_session):
    from app.workers.ingest import SourceNotConfigured
    import pytest

    with pytest.raises(SourceNotConfigured):
        ingest_source(db_session, "no_existe", SearchQuery(term="x", enrich=False))


# ---------------------------------------------------------------------------
# Falla de adapter completa (SourceUnavailable tras agotar reintentos): se propaga y
# NO se marca last_success_at, pero last_run_at/last_error si se actualizan.
# ---------------------------------------------------------------------------


@respx.mock
def test_full_adapter_failure_propagates_and_does_not_set_last_success(db_session):
    import pytest

    from app.adapters.errors import SourceUnavailable

    source = _make_source(db_session)
    respx.get(f"{BASE_URL}/sites/MLA/search").mock(return_value=httpx.Response(500))

    with pytest.raises(SourceUnavailable):
        ingest_source(db_session, source.slug, SearchQuery(term="iphone", enrich=False))

    db_session.refresh(source)
    assert source.last_run_at is not None
    assert source.last_success_at is None
    assert source.last_error is not None
    assert db_session.query(Listing).count() == 0

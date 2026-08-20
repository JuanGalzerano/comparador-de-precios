"""Tests de la corrida diaria (`app/workers/daily.py`).

Sin red: se sustituye `run_ingest`, que es lo unico del modulo que sale a internet.
Lo que se prueba es el contrato del orquestador — a quien llama, en que orden, y sobre
todo que una fuente caida no arrastre a las demas.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from app.enums import SourceKind, SourceStatus
from app.models.listing import Listing
from app.models.retailer_source import RetailerSource
from app.workers import daily
from app.workers.ingest import IngestRunResult


def _fuente(db: Session, slug: str, status: SourceStatus = SourceStatus.ACTIVE) -> RetailerSource:
    source = RetailerSource(
        slug=slug,
        display_name=slug.title(),
        kind=SourceKind.VTEX,
        status=status,
        config_json={"base_url": f"https://{slug}.test"},
    )
    db.add(source)
    db.commit()
    return source


def _publicacion(db: Session, source: RetailerSource, external_id: str) -> Listing:
    listing = Listing(
        retailer_source_id=source.id,
        external_id=external_id,
        title=f"Producto {external_id}",
        permalink=f"https://{source.slug}.test/p/{external_id}",
        price=Decimal("1000"),
        fetched_at=datetime.now(timezone.utc),
    )
    db.add(listing)
    db.commit()
    return listing


@pytest.fixture()
def sin_matcher_ni_mantenimiento(monkeypatch):
    """Aisla el orquestador: el matcher y el mantenimiento tienen sus propios tests."""
    import app.matching.matcher as matcher
    import app.services.maintenance as maintenance

    monkeypatch.setattr(matcher, "match_listings", lambda db: "sin cambios")
    monkeypatch.setattr(maintenance, "run_maintenance", lambda db: "sin cambios")


def test_omite_fuentes_sin_publicaciones(db_session, sin_matcher_ni_mantenimiento):
    """Una fuente recien agregada no tiene nada que refrescar: se omite, no falla."""
    _fuente(db_session, "vacia")

    report = daily.run_daily(db_session)

    outcome = next(o for o in report.outcomes if o.slug == "vacia")
    assert outcome.status == "OMITIDA"
    assert not report.failed


def test_refresca_las_fuentes_con_publicaciones(db_session, monkeypatch, sin_matcher_ni_mantenimiento):
    source = _fuente(db_session, "tienda")
    _publicacion(db_session, source, "abc")

    llamadas = []

    def _fake(db, src, request):
        llamadas.append((src.slug, list(request.external_ids)))
        return IngestRunResult(source_slug=src.slug, updated=1, price_points_added=1)

    monkeypatch.setattr(daily, "run_ingest", _fake)

    report = daily.run_daily(db_session)

    assert llamadas == [("tienda", ["abc"])]
    outcome = report.outcomes[0]
    assert outcome.status == "OK"
    assert outcome.refreshed == 1
    assert outcome.price_points == 1


def test_una_fuente_caida_no_frena_a_las_otras(db_session, monkeypatch, sin_matcher_ni_mantenimiento):
    """Es la razon de ser del try por fuente: si Fravega esta caida, las otras ocho
    tienen que actualizarse igual."""
    caida = _fuente(db_session, "caida")
    sana = _fuente(db_session, "sana")
    _publicacion(db_session, caida, "x")
    _publicacion(db_session, sana, "y")

    def _fake(db, src, request):
        if src.slug == "caida":
            raise RuntimeError("la tienda no responde")
        return IngestRunResult(source_slug=src.slug, updated=1)

    monkeypatch.setattr(daily, "run_ingest", _fake)

    report = daily.run_daily(db_session)

    por_slug = {o.slug: o for o in report.outcomes}
    assert por_slug["caida"].status == "ERROR"
    assert "la tienda no responde" in por_slug["caida"].error
    assert por_slug["sana"].status == "OK"
    assert report.failed == ["caida"]


def test_ignora_las_fuentes_no_activas(db_session, monkeypatch, sin_matcher_ni_mantenimiento):
    """MercadoLibre esta bloqueada: refrescarla seria gastar requests en un 403 seguro."""
    bloqueada = _fuente(db_session, "bloqueada", status=SourceStatus.BLOCKED_TOS_REVIEW)
    _publicacion(db_session, bloqueada, "z")

    monkeypatch.setattr(daily, "run_ingest", lambda *a, **k: pytest.fail("no deberia correr"))

    report = daily.run_daily(db_session)

    assert report.outcomes == []


def test_only_acota_a_las_fuentes_pedidas(db_session, monkeypatch, sin_matcher_ni_mantenimiento):
    a = _fuente(db_session, "una")
    b = _fuente(db_session, "otra")
    _publicacion(db_session, a, "1")
    _publicacion(db_session, b, "2")

    monkeypatch.setattr(
        daily, "run_ingest", lambda db, src, req: IngestRunResult(source_slug=src.slug)
    )

    report = daily.run_daily(db_session, only=["una"])

    assert [o.slug for o in report.outcomes] == ["una"]


def test_dry_run_no_toca_nada(db_session, monkeypatch):
    source = _fuente(db_session, "tienda")
    _publicacion(db_session, source, "abc")

    monkeypatch.setattr(daily, "run_ingest", lambda *a, **k: pytest.fail("no deberia correr"))

    report = daily.run_daily(db_session, dry_run=True)

    assert report.outcomes[0].status == "OMITIDA"
    assert "1 publicaciones" in report.outcomes[0].skipped_reason
    assert report.matched is None
    assert report.maintenance is None


def test_el_reporte_se_puede_leer(db_session, monkeypatch, sin_matcher_ni_mantenimiento):
    """El resumen es lo unico que ve quien mira el log del cron a la mañana."""
    source = _fuente(db_session, "tienda")
    _publicacion(db_session, source, "abc")
    monkeypatch.setattr(
        daily,
        "run_ingest",
        lambda db, src, req: IngestRunResult(source_slug=src.slug, updated=3, price_points_added=2),
    )

    texto = daily.run_daily(db_session).render()

    assert "tienda" in texto
    assert "3 publicaciones" in texto
    assert "2 puntos de historial" in texto


def test_una_fuente_sin_refresh_no_cuenta_como_fallo(db_session, monkeypatch, sin_matcher_ni_mantenimiento):
    """Megatone no permite pedir por id y nunca va a permitirlo.

    Si eso figura como ERROR, la tarea programada reporta fallo todos los días — y un
    error que suena siempre deja de escucharse.
    """
    from app.adapters.errors import UnsupportedFetchMode

    source = _fuente(db_session, "megatone")
    _publicacion(db_session, source, "m1")

    def _fake(db, src, request):
        raise UnsupportedFetchMode("no soporta refresh", source_slug=src.slug)

    monkeypatch.setattr(daily, "run_ingest", _fake)

    report = daily.run_daily(db_session)

    assert report.outcomes[0].status == "OMITIDA"
    assert report.failed == [], "no puede contar como fallo de la corrida"


def test_only_con_un_slug_inexistente_avisa(db_session, sin_matcher_ni_mantenimiento):
    """Un typo devolvía un reporte vacío y código 0: idéntico a una corrida exitosa."""
    with pytest.raises(daily.FuenteDesconocida, match="fravgea"):
        daily.run_daily(db_session, only=["fravgea"])


def test_el_matcher_caido_no_se_lleva_el_resumen(db_session, monkeypatch):
    """El resumen es lo único que queda de una corrida de dos minutos: tiene que llegar."""
    import app.matching.matcher as matcher
    import app.services.maintenance as maintenance

    source = _fuente(db_session, "tienda")
    _publicacion(db_session, source, "abc")
    monkeypatch.setattr(
        daily, "run_ingest", lambda db, src, req: IngestRunResult(source_slug=src.slug, updated=1)
    )

    def _explota(db):
        raise RuntimeError("el matcher reventó")

    monkeypatch.setattr(matcher, "match_listings", _explota)
    monkeypatch.setattr(maintenance, "run_maintenance", lambda db: "ok")

    report = daily.run_daily(db_session)

    assert report.outcomes[0].status == "OK", "lo refrescado tiene que seguir reportado"
    assert "FALLO" in report.matched
    assert report.maintenance == "ok", "el mantenimiento tiene que correr igual"

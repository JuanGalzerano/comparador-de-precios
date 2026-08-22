"""Tests de disponibilidad: lo que no se puede comprar no entra a la comparación.

El caso que motiva todo esto: las tiendas dejan productos descontinuados en su catálogo
con el precio de hace años. Jumbo publica un Smart TV Philips 43" a $54.999 y un LED 50"
a $13.499, ambos con `AvailableQuantity: 0`. Como el sitio ordena de más barato a más
caro, esos zombis ganaban siempre y aparecían como la mejor oferta.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.adapters.types import NormalizedListingInput
from app.enums import SourceKind, SourceStatus
from app.models.listing import Listing
from app.models.retailer_source import RetailerSource
from app.workers.ingest import _upsert_listing, IngestRunResult


def _fuente(db) -> RetailerSource:
    source = RetailerSource(
        slug="tienda",
        display_name="Tienda",
        kind=SourceKind.VTEX,
        status=SourceStatus.ACTIVE,
        config_json={"base_url": "https://tienda.test"},
    )
    db.add(source)
    db.flush()
    return source


def _normalizada(**extra) -> NormalizedListingInput:
    campos = {
        "source_slug": "tienda",
        "external_id": "abc",
        "title": 'Smart Tv Philips 43" 43pfg5813',
        "permalink": "https://tienda.test/p/abc",
        "price": Decimal("54999"),
    }
    campos.update(extra)
    return NormalizedListingInput(**campos)


def test_por_defecto_una_publicacion_esta_disponible():
    """La mayoría de las fuentes no informan stock: el default no puede ser 'agotado'."""
    assert _normalizada().available is True


def test_sin_stock_queda_marcada(db_session):
    source = _fuente(db_session)
    _upsert_listing(db_session, source, _normalizada(available=False), IngestRunResult(source_slug="tienda"))

    listing = db_session.scalars(select(Listing)).one()
    assert listing.unavailable_since is not None


def test_con_stock_no_queda_marcada(db_session):
    source = _fuente(db_session)
    _upsert_listing(db_session, source, _normalizada(available=True), IngestRunResult(source_slug="tienda"))

    assert db_session.scalars(select(Listing)).one().unavailable_since is None


def test_si_la_tienda_repone_vuelve_a_la_comparacion(db_session):
    """No se borra la publicación: si vuelve el stock, vuelve sola."""
    source = _fuente(db_session)
    r = IngestRunResult(source_slug="tienda")
    _upsert_listing(db_session, source, _normalizada(available=False), r)
    _upsert_listing(db_session, source, _normalizada(available=True), r)

    assert db_session.scalars(select(Listing)).one().unavailable_since is None


def test_conserva_desde_cuando_esta_caida(db_session):
    """Interesa desde CUÁNDO no se puede comprar, no la última vez que se confirmó."""
    source = _fuente(db_session)
    r = IngestRunResult(source_slug="tienda")
    ayer = datetime.now(timezone.utc) - timedelta(days=1)

    _upsert_listing(db_session, source, _normalizada(available=False, fetched_at=ayer), r)
    primera = db_session.scalars(select(Listing)).one().unavailable_since

    _upsert_listing(db_session, source, _normalizada(available=False), r)
    segunda = db_session.scalars(select(Listing)).one().unavailable_since

    assert segunda == primera, "la fecha original no puede pisarse en cada corrida"


def test_la_busqueda_no_devuelve_lo_que_no_se_puede_comprar(client, seeded_db):
    """El test de fondo: un producto agotado no puede figurar como la mejor oferta."""
    listing = seeded_db.scalars(select(Listing)).first()
    antes = client.get("/search", params={"q": "iphone", "live": "false"}).json()["total"]

    listing.unavailable_since = datetime.now(timezone.utc)
    seeded_db.commit()

    despues = client.get("/search", params={"q": "iphone", "live": "false"}).json()
    assert despues["total"] <= antes
    for cluster in despues["items"]:
        assert cluster["listing_count"] >= 1

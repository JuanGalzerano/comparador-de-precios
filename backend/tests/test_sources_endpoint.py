"""Tests de `GET /sources` y de los órdenes nuevos de `/search`.

La métrica que se prueba es `win_rate`: qué fracción de los productos DISPUTADOS
(publicados por al menos dos tiendas) tiene esta tienda al precio más bajo. Los
productos con una sola fuente no cuentan — es la parte del cálculo fácil de romper sin
que se note.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.enums import ItemCondition, SourceKind, SourceStatus, WarrantyType
from app.models.listing import Listing
from app.models.product import Product
from app.models.retailer_source import RetailerSource


def _source(db: Session, slug: str) -> RetailerSource:
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


def _product(db: Session, title: str) -> Product:
    product = Product(canonical_title=title, attributes_json={})
    db.add(product)
    db.flush()
    return product


def _listing(db: Session, source: RetailerSource, product: Product, price: str) -> Listing:
    listing = Listing(
        product_id=product.id,
        retailer_source_id=source.id,
        external_id=f"{source.slug}-{product.id}",
        title=product.canonical_title,
        permalink="https://example.test/item",
        condition=ItemCondition.NEW,
        price=Decimal(price),
        warranty_type=WarrantyType.UNKNOWN,
        fetched_at=datetime.now(timezone.utc),
    )
    db.add(listing)
    db.flush()
    return listing


def test_win_rate_counts_only_contested_products(db_session: Session, client: TestClient) -> None:
    barata = _source(db_session, "barata")
    cara = _source(db_session, "cara")

    for i in range(3):
        disputado = _product(db_session, f"Producto disputado {i}")
        _listing(db_session, barata, disputado, "100")
        _listing(db_session, cara, disputado, "200")

    # Producto exclusivo de "cara": es el más barato porque es el único, y eso no
    # debe contar como una victoria.
    solo = _product(db_session, "Producto exclusivo")
    _listing(db_session, cara, solo, "999")
    db_session.commit()

    items = {s["slug"]: s for s in client.get("/sources").json()["items"]}

    assert items["barata"]["win_rate"] == 1.0
    assert items["barata"]["cheapest_count"] == 3
    assert items["cara"]["win_rate"] == 0.0
    assert items["cara"]["cheapest_count"] == 0
    assert items["cara"]["product_count"] == 4  # el exclusivo sí cuenta como producto


def test_source_without_listings_has_no_win_rate(db_session: Session, client: TestClient) -> None:
    _source(db_session, "vacia")
    db_session.commit()

    items = {s["slug"]: s for s in client.get("/sources").json()["items"]}

    assert items["vacia"]["win_rate"] is None
    assert items["vacia"]["listing_count"] == 0


def test_search_min_retailers_excludes_single_store_products(
    db_session: Session, client: TestClient
) -> None:
    una = _source(db_session, "una")
    otra = _source(db_session, "otra")

    compartido = _product(db_session, "Producto en dos tiendas")
    _listing(db_session, una, compartido, "500")
    _listing(db_session, otra, compartido, "700")

    exclusivo = _product(db_session, "Producto en una sola tienda")
    _listing(db_session, una, exclusivo, "100")
    db_session.commit()

    todos = client.get("/search").json()
    comparables = client.get("/search", params={"min_retailers": 2}).json()

    assert {item["canonical_title"] for item in todos["items"]} == {
        "Producto en dos tiendas",
        "Producto en una sola tienda",
    }
    assert [item["canonical_title"] for item in comparables["items"]] == [
        "Producto en dos tiendas"
    ]
    assert comparables["total"] == 1
    assert comparables["items"][0]["retailer_count"] == 2
    assert sorted(comparables["items"][0]["retailer_names"]) == ["Otra", "Una"]


def test_search_sort_spread_puts_biggest_gap_first(
    db_session: Session, client: TestClient
) -> None:
    una = _source(db_session, "una")
    otra = _source(db_session, "otra")

    chico = _product(db_session, "Diferencia chica")
    _listing(db_session, una, chico, "1000")
    _listing(db_session, otra, chico, "1100")

    grande = _product(db_session, "Diferencia grande")
    _listing(db_session, una, grande, "2000")
    _listing(db_session, otra, grande, "5000")
    db_session.commit()

    items = client.get("/search", params={"sort": "spread"}).json()["items"]

    assert [item["canonical_title"] for item in items][:2] == [
        "Diferencia grande",
        "Diferencia chica",
    ]

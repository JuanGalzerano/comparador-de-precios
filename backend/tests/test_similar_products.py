"""Tests de `GET /products/{id}/similar`.

Los "similares" son productos PARECIDOS, no el mismo. Existen porque agruparlos en el
cluster haría mentir al cartel de "ahorrás hasta X" (compararía cosas distintas), pero
esconderlos pierde información útil para el comprador.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.enums import ItemCondition, MatchMethod, SourceKind, SourceStatus, WarrantyType
from app.models.listing import Listing
from app.models.product import Product
from app.models.product_match import ProductMatch
from app.models.retailer_source import RetailerSource


def _source(db: Session, slug: str = "cetrogar") -> RetailerSource:
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


def _product_with_listing(
    db: Session, source: RetailerSource, title: str, price: str
) -> tuple[Product, Listing]:
    product = Product(canonical_title=title, attributes_json={})
    db.add(product)
    db.flush()
    listing = Listing(
        product_id=product.id,
        retailer_source_id=source.id,
        external_id=f"ext-{product.id}",
        title=title,
        permalink="https://example.test/x",
        condition=ItemCondition.NEW,
        price=Decimal(price),
        warranty_type=WarrantyType.UNKNOWN,
        fetched_at=datetime.now(timezone.utc),
    )
    db.add(listing)
    db.flush()
    return product, listing


def _link(db: Session, listing: Listing, candidate: Product, confidence: float) -> None:
    """Registra que el matcher consideró `candidate` para `listing` y no lo aplicó."""
    db.add(
        ProductMatch(
            listing_id=listing.id,
            product_id=candidate.id,
            method=MatchMethod.FUZZY,
            confidence=confidence,
        )
    )
    db.flush()


def test_returns_the_candidate_the_matcher_rejected(
    db_session: Session, client: TestClient
) -> None:
    source = _source(db_session)
    base, base_listing = _product_with_listing(
        db_session, source, "iPhone 15 128GB Black", "1699999"
    )
    similar, _ = _product_with_listing(
        db_session, source, "Reacondicionado iPhone 15 128 GB", "1032952"
    )
    _link(db_session, base_listing, similar, 0.43)
    db_session.commit()

    body = client.get(f"/products/{base.id}/similar").json()

    assert [item["id"] for item in body["items"]] == [similar.id]
    assert body["items"][0]["confidence"] == 0.43
    assert body["items"][0]["min_final_price"] == "1032952.00"


def test_relationship_works_in_both_directions(db_session: Session, client: TestClient) -> None:
    """Da igual de qué lado salió el candidato: la similitud es simétrica."""
    source = _source(db_session)
    base, _ = _product_with_listing(db_session, source, "iPhone 15 128GB Black", "1699999")
    other, other_listing = _product_with_listing(
        db_session, source, "iPhone 15 Plus 128 GB", "1899999"
    )
    # El match salió de una publicación del OTRO producto apuntando al de la ficha.
    _link(db_session, other_listing, base, 0.41)
    db_session.commit()

    body = client.get(f"/products/{base.id}/similar").json()

    assert [item["id"] for item in body["items"]] == [other.id]


def test_accessories_are_filtered_out_by_price(db_session: Session, client: TestClient) -> None:
    """Una funda comparte casi todo el título con el teléfono, pero no es una alternativa.

    Caso real: "FUNDA IPHONE 15 TRANSPARENTE MAGSAFE" a $17.250 aparecía como similar de
    un iPhone 15 de $1.699.999.
    """
    source = _source(db_session)
    base, base_listing = _product_with_listing(
        db_session, source, "iPhone 15 128GB Black", "1699999"
    )
    funda, _ = _product_with_listing(
        db_session, source, "FUNDA IPHONE 15 TRANSPARENTE MAGSAFE", "17250"
    )
    _link(db_session, base_listing, funda, 0.40)
    db_session.commit()

    body = client.get(f"/products/{base.id}/similar").json()

    assert body["items"] == []


def test_a_cheaper_but_comparable_model_is_kept(db_session: Session, client: TestClient) -> None:
    """El filtro de precio no puede tragarse las alternativas legítimamente más baratas."""
    source = _source(db_session)
    base, base_listing = _product_with_listing(
        db_session, source, "Notebook Acer i5 16GB 512GB", "1500000"
    )
    barata, _ = _product_with_listing(
        db_session, source, "Notebook Acer i3 8GB 512GB", "900000"
    )
    _link(db_session, base_listing, barata, 0.44)
    db_session.commit()

    body = client.get(f"/products/{base.id}/similar").json()

    assert [item["id"] for item in body["items"]] == [barata.id]


def test_products_without_listings_are_not_offered(db_session: Session, client: TestClient) -> None:
    """Un candidato que se quedó sin publicaciones no tiene precio que mostrar."""
    source = _source(db_session)
    base, base_listing = _product_with_listing(db_session, source, "Producto base", "100000")
    vacio = Product(canonical_title="Producto sin publicaciones", attributes_json={})
    db_session.add(vacio)
    db_session.flush()
    _link(db_session, base_listing, vacio, 0.42)
    db_session.commit()

    body = client.get(f"/products/{base.id}/similar").json()

    assert body["items"] == []


def test_the_product_itself_is_never_listed_as_similar(
    db_session: Session, client: TestClient
) -> None:
    source = _source(db_session)
    base, base_listing = _product_with_listing(db_session, source, "Producto base", "100000")
    _link(db_session, base_listing, base, 1.0)
    db_session.commit()

    body = client.get(f"/products/{base.id}/similar").json()

    assert body["items"] == []


def test_unknown_product_is_404(client: TestClient) -> None:
    assert client.get("/products/999999/similar").status_code == 404

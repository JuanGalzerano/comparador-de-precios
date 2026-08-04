"""Tests del matcher cross-retailer (`app/matching/`).

Los títulos de los casos son títulos REALES traídos de Frávega, Cetrogar y Naldo (la
corrida de ingesta del 2026-08-04), no ejemplos inventados: lo que se prueba es que el
matcher agrupa lo que un humano agruparía mirando esos mismos títulos.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from app.enums import ItemCondition, SourceKind, SourceStatus, WarrantyType
from app.matching.matcher import match_listings
from app.matching.normalize import (
    extract_brand,
    extract_capacity_gb,
    extract_model_codes,
    extract_screen_inches,
    extract_variants,
    jaccard,
    tokens_for_similarity,
)
from app.models.listing import Listing
from app.models.product import Product
from app.models.retailer_source import RetailerSource


# --- normalize -------------------------------------------------------------


@pytest.mark.parametrize(
    "title,expected",
    [
        ("Apple iPhone 13 128GB Midnight", 128),
        ("Notebook HP 15,6\" AMD Ryzen 5 8GB 512GB", 512),
        ("Smart Tv TCL 50 50s5k Fhd Qled", None),
        ("Disco Externo 1 TB USB", 1024),
    ],
)
def test_extract_capacity(title: str, expected: int | None) -> None:
    assert extract_capacity_gb(title) == expected


def test_extract_screen_inches() -> None:
    assert extract_screen_inches('Smart TV 50" 4K Ultra HD Motorola') == 50.0
    assert extract_screen_inches("Notebook HP 15.6 pulgadas") == 15.6


def test_extract_brand_ignores_unknown_words() -> None:
    assert extract_brand("Smartphone Apple iPhone 13 Mini 128GB") == "apple"
    assert extract_brand("Notebook Exo R35 15.6\"") is None


def test_variants_distinguish_pro_and_mini() -> None:
    assert extract_variants("Apple iPhone 13 Mini 128 GB") == frozenset({"mini"})
    assert extract_variants("iPhone 13 128GB Midnight") == frozenset()


def test_model_codes_survive_formatting_differences() -> None:
    a = extract_model_codes("Notebook HP 15-fc0235la 15.6'' Ryzen 3")
    b = extract_model_codes("Notebook HP 15,6 AMD Ryzen 3 8GB 512GB 15-fc0235la")
    assert a & b


def test_color_does_not_affect_similarity() -> None:
    a = tokens_for_similarity("iPhone 13 128GB Midnight")
    b = tokens_for_similarity("iPhone 13 128GB Starlight")
    assert jaccard(a, b) == 1.0


# --- matcher ---------------------------------------------------------------


def _source(db: Session, slug: str) -> RetailerSource:
    source = RetailerSource(
        slug=slug,
        display_name=slug.title(),
        kind=SourceKind.VTEX,
        status=SourceStatus.ACTIVE,
        config_json={},
    )
    db.add(source)
    db.flush()
    return source


def _listing(db: Session, source: RetailerSource, title: str, price: str) -> Listing:
    listing = Listing(
        retailer_source_id=source.id,
        external_id=f"{source.slug}-{title[:20]}",
        title=title,
        permalink=f"https://example.test/{source.slug}",
        condition=ItemCondition.NEW,
        price=Decimal(price),
        shipping_cost=None,
        warranty_type=WarrantyType.UNKNOWN,
        fetched_at=datetime.now(timezone.utc),
    )
    db.add(listing)
    db.flush()
    return listing


def _product_of(db: Session, listing: Listing) -> int | None:
    db.refresh(listing)
    return listing.product_id


def test_same_product_across_stores_lands_in_one_cluster(db_session: Session) -> None:
    a = _source(db_session, "cetrogar")
    b = _source(db_session, "naldo")
    first = _listing(db_session, a, "Apple iPhone 13 128GB 6.1 Pulgadas", "1285000")
    second = _listing(db_session, b, "iPhone 13 128GB Midnight", "1399999")

    stats = match_listings(db_session)

    assert stats.listings_seen == 2
    assert _product_of(db_session, first) == _product_of(db_session, second)
    assert db_session.query(Product).count() == 1


def test_different_capacity_is_a_different_product(db_session: Session) -> None:
    a = _source(db_session, "cetrogar")
    b = _source(db_session, "naldo")
    small = _listing(db_session, a, "Apple iPhone 13 128GB Midnight", "1285000")
    large = _listing(db_session, b, "Apple iPhone 13 256GB Midnight", "1585000")

    match_listings(db_session)

    assert _product_of(db_session, small) != _product_of(db_session, large)


def test_mini_variant_is_not_the_base_model(db_session: Session) -> None:
    a = _source(db_session, "cetrogar")
    b = _source(db_session, "naldo")
    base = _listing(db_session, a, "Apple iPhone 13 128 GB", "1285000")
    mini = _listing(db_session, b, "Apple iPhone 13 Mini 128 GB", "1085000")

    match_listings(db_session)

    assert _product_of(db_session, base) != _product_of(db_session, mini)


def test_different_manufacturer_code_is_a_different_product(db_session: Session) -> None:
    a = _source(db_session, "cetrogar")
    b = _source(db_session, "naldo")
    ryzen3 = _listing(db_session, a, "Notebook HP 15-fc0235la 15.6 Ryzen 3 8 GB 512 GB", "900000")
    ryzen5 = _listing(db_session, b, "Notebook HP 15-fc0251la 15.6 Ryzen 5 8 GB 512 GB", "1100000")

    match_listings(db_session)

    assert _product_of(db_session, ryzen3) != _product_of(db_session, ryzen5)


def test_different_brands_never_merge(db_session: Session) -> None:
    a = _source(db_session, "cetrogar")
    b = _source(db_session, "naldo")
    samsung = _listing(db_session, a, "Smart TV Samsung 50 4k Uhd", "700000")
    philips = _listing(db_session, b, "Smart TV Philips 50 4k Uhd", "690000")

    match_listings(db_session)

    assert _product_of(db_session, samsung) != _product_of(db_session, philips)


def test_only_unmatched_leaves_existing_assignments_alone(db_session: Session) -> None:
    source = _source(db_session, "cetrogar")
    listing = _listing(db_session, source, "Apple iPhone 13 128GB", "1285000")
    match_listings(db_session)
    original = _product_of(db_session, listing)

    stats = match_listings(db_session)

    assert stats.listings_seen == 0
    assert _product_of(db_session, listing) == original

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


def test_shared_manufacturer_code_beats_a_low_title_similarity(db_session: Session) -> None:
    """El código de fabricante compartido alcanza para agrupar, sin importar el Jaccard.

    Caso real detectado en auditoría: estos dos títulos comparten `UN50U8000F` pero solo
    0.33 de similitud de tokens, así que caían en dos clusters de una tienda cada uno —
    justo lo contrario de lo que el comparador tiene que hacer.
    """
    a = _source(db_session, "cetrogar")
    b = _source(db_session, "naldo")
    uno = _listing(db_session, a, "Smart TV Samsung UN50U8000F 50 pulgadas 4K", "759999")
    otro = _listing(db_session, b, 'Samsung Smart TV 50" UN50U8000F UHD', "1199999")

    match_listings(db_session)

    assert _product_of(db_session, uno) == _product_of(db_session, otro)
    assert db_session.query(Product).count() == 1


def test_catalog_id_groups_listings_deterministically(db_session: Session) -> None:
    """Con el mismo `catalog_product_id` no se mira el título en absoluto."""
    a = _source(db_session, "mercadolibre")
    b = _source(db_session, "otra")
    uno = _listing(db_session, a, "Apple iPhone 13 128 GB Midnight", "1000000")
    uno.catalog_product_id = "MLA22811322"
    otro = _listing(db_session, b, "Celular Apple 13 negro 128", "1100000")
    otro.catalog_product_id = "MLA22811322"
    db_session.flush()

    stats = match_listings(db_session)

    assert _product_of(db_session, uno) == _product_of(db_session, otro)
    assert stats.matched_by_catalog == 1


def test_rematch_all_actually_merges_previously_split_clusters(db_session: Session) -> None:
    """`--all` tiene que poder fusionar lo que una corrida anterior dejó separado.

    Antes era un no-op: cada publicación volvía a encontrar el producto singleton que el
    propio matcher le había creado (título idéntico -> Jaccard 1.0) y se re-asignaba a sí
    misma, así que bajar el umbral no fusionaba nada.
    """
    import app.matching.matcher as matcher_mod

    a = _source(db_session, "cetrogar")
    b = _source(db_session, "naldo")
    uno = _listing(db_session, a, "Lavarropas Drean Next 8kg carga frontal", "700000")
    otro = _listing(db_session, b, "Lavarropas Drean 8 kg blanco", "800000")

    match_listings(db_session)
    assert _product_of(db_session, uno) != _product_of(db_session, otro)

    original = matcher_mod.AUTO_MATCH_THRESHOLD
    matcher_mod.AUTO_MATCH_THRESHOLD = 0.2
    try:
        match_listings(db_session, only_unmatched=False)
    finally:
        matcher_mod.AUTO_MATCH_THRESHOLD = original

    assert _product_of(db_session, uno) == _product_of(db_session, otro)
    # El producto que quedó vacío no debe seguir apareciendo en las búsquedas.
    assert db_session.query(Product).count() == 1


def test_auto_created_products_do_not_pollute_the_review_queue(db_session: Session) -> None:
    """Un producto creado sin comparar contra nada no es evidencia de match."""
    from app.models.product_match import ProductMatch

    source = _source(db_session, "cetrogar")
    _listing(db_session, source, "Producto único sin par", "100000")

    match_listings(db_session)

    assert db_session.query(ProductMatch).count() == 0


def test_long_titles_are_truncated_to_the_column_length(db_session: Session) -> None:
    """Postgres aborta la transacción con títulos largos; SQLite no dice nada."""
    source = _source(db_session, "cetrogar")
    _listing(db_session, source, "Notebook " + "x" * 900, "100000")

    match_listings(db_session)

    product = db_session.query(Product).one()
    assert len(product.canonical_title) <= 512
    assert product.model is None or len(product.model) <= 128


def test_different_iphone_generations_never_merge(db_session: Session) -> None:
    """El número de generación es lo único que separa un iPhone 13 de un 15.

    Caso real: el cluster del iPhone 13 se había comido publicaciones de iPhone 14 y 15
    (Jaccard 0.5, por encima del umbral), y la ficha mostraba "desde $696.622 hasta
    $1.699.999" comparando tres teléfonos distintos.
    """
    a = _source(db_session, "fravega")
    b = _source(db_session, "naldo")
    trece = _listing(db_session, a, "iPhone 13 128GB Midnight", "1399999")
    catorce = _listing(db_session, b, "iPhone 14 - 128GB", "1299999")
    quince = _listing(db_session, b, "iPhone 15 128GB Black", "1699999")

    match_listings(db_session)

    productos = {
        _product_of(db_session, trece),
        _product_of(db_session, catorce),
        _product_of(db_session, quince),
    }
    assert len(productos) == 3


def test_same_generation_still_merges_across_stores(db_session: Session) -> None:
    """La guarda de generación no debe romper el caso que sí tiene que agrupar."""
    a = _source(db_session, "fravega")
    b = _source(db_session, "naldo")
    uno = _listing(db_session, a, "iPhone 13 128GB Midnight", "1399999")
    otro = _listing(db_session, b, "Reacondicionado iPhone 13 Apple 128 GB 6.1", "696622")

    match_listings(db_session)

    assert _product_of(db_session, uno) == _product_of(db_session, otro)


def test_two_tvs_of_the_same_brand_and_size_are_not_the_same_product(
    db_session: Session,
) -> None:
    """Mismo tamaño y marca, distinta línea: el código corto (`S90D`) los separa."""
    a = _source(db_session, "cetrogar")
    b = _source(db_session, "cetrogar2")
    qled = _listing(db_session, a, 'Smart TV LED 55" Samsung QN55Q6FAAGCZB 4K HDR', "949999")
    oled = _listing(db_session, b, 'Smart TV LED 55" Samsung OLED S90D 4K', "3699999")

    match_listings(db_session)

    assert _product_of(db_session, qled) != _product_of(db_session, oled)


def test_shared_incidental_number_does_not_merge_two_generations(db_session: Session) -> None:
    """Compartir un número suelto (RAM, pulgadas) no alcanza para ser el mismo producto.

    Caso real: "iPhone 15 Pro Max 256 GB 8" y "iPhone 16 Pro Max 256 GB 8" compartían el
    8, así que con la regla de "intersección no vacía" se fusionaban igual.
    """
    a = _source(db_session, "naldo")
    b = _source(db_session, "fravega")
    quince = _listing(db_session, a, "Reacondicionado iPhone Apple 15 Pro Max 256 GB 8", "1834822")
    dieciseis = _listing(db_session, b, "Reacondicionado iPhone Apple 16 Pro Max 256 GB 8", "2329482")

    match_listings(db_session)

    assert _product_of(db_session, quince) != _product_of(db_session, dieciseis)


def test_extra_numbers_on_one_side_do_not_block_a_match(db_session: Session) -> None:
    """Un título más detallado que el otro sigue siendo el mismo producto."""
    a = _source(db_session, "cetrogar")
    b = _source(db_session, "fravega")
    largo = _listing(db_session, a, "Notebook HP 15-fc0235la 15.6 Ryzen 3 7320U 8 GB 512 GB", "1289999")
    corto = _listing(db_session, b, "Notebook HP 15,6 AMD Ryzen 3 8GB 512GB 15-fc0235la", "949999")

    match_listings(db_session)

    assert _product_of(db_session, largo) == _product_of(db_session, corto)


def test_wattage_is_not_a_model_code(db_session: Session) -> None:
    """"800W" describe la potencia de cualquier aparato, no identifica un producto.

    Caso real: con `800w` tratado como código de fabricante, y aceptando coincidencia
    por contención (`800w` ⊂ `2800w`), una tostadora terminó dentro del cluster de un
    aire acondicionado.
    """
    a = _source(db_session, "fravega")
    b = _source(db_session, "cetrogar")
    tostadora = _listing(db_session, a, "Tostadora Kanji Blanca 800W KJH-TM800-04", "23999")
    aire = _listing(db_session, b, "Aire Acondicionado Split BGH 2800W FC BS26WCDW", "719999")

    match_listings(db_session)

    assert _product_of(db_session, tostadora) != _product_of(db_session, aire)


def test_rpm_shared_between_brands_does_not_merge(db_session: Session) -> None:
    """Dos lavarropas de 1000 RPM de marcas distintas no son el mismo producto."""
    a = _source(db_session, "fravega")
    b = _source(db_session, "cetrogar")
    midea = _listing(db_session, a, "Lavarropas Midea Carga Frontal 6kg 1000rpm MF100W60", "529999")
    philco = _listing(db_session, b, "Lavarropas Philco PHLF61BN 6 KG 1000RPM CF blanco", "669999")

    match_listings(db_session)

    assert _product_of(db_session, midea) != _product_of(db_session, philco)


def test_containment_still_works_for_long_codes(db_session: Session) -> None:
    """La contención sigue valiendo cuando el código es largo: `50a64n` ⊂ `9150a64n`."""
    a = _source(db_session, "fravega")
    b = _source(db_session, "cetrogar")
    uno = _listing(db_session, a, 'Smart TV 50" Hisense HD LED VIDAA 50A64N', "579999")
    otro = _listing(db_session, b, "Smart TV LED 50'' Hisense 9150A64N 4K HDR", "699999")

    match_listings(db_session)

    assert _product_of(db_session, uno) == _product_of(db_session, otro)


def test_same_tv_line_in_two_sizes_stays_separate(db_session: Session) -> None:
    """Un TV de 50" y uno de 55" de la misma línea comparten código de fabricante.

    `50PUD7309/77` y `PUD7309/77` se solapan por contención, así que el código los
    unía. El tamaño es lo único que los distingue, y muchas tiendas lo escriben sin
    unidad ("Philips 55 Pud7309/77"), por eso se compara como número suelto.
    """
    a = _source(db_session, "cetrogar")
    b = _source(db_session, "naldo")
    cincuenta = _listing(db_session, a, "TV LED 50'' 50PUD7309/77 4K HDR Philips", "699999")
    cincuenta_cinco = _listing(
        db_session, b, "Smart Tv Philips 55 Pud7309/77 4k Uhd Titan Tv", "769999"
    )

    match_listings(db_session)

    assert _product_of(db_session, cincuenta) != _product_of(db_session, cincuenta_cinco)


def test_same_tv_across_stores_still_merges(db_session: Session) -> None:
    """La guarda de tamaño no puede romper el caso que sí tiene que agrupar."""
    a = _source(db_session, "cetrogar")
    b = _source(db_session, "fravega")
    uno = _listing(db_session, a, "TV LED 50'' 50PUD7309/77 4K HDR Philips", "699999")
    otro = _listing(
        db_session, b, "Smart TV Philips LED 50” 4K UHD Titan OS 50PUD7309/77", "659999"
    )

    match_listings(db_session)

    assert _product_of(db_session, uno) == _product_of(db_session, otro)

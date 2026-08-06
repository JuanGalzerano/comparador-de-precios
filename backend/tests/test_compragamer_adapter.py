"""Tests del adapter de Compra Gamer.

Lo importante acá es la **escala del precio**: la fuente publica pesos enteros
(`2882400` = $ 2.882.400). Una fuente que publicara en centavos o en miles ensuciaría
todas las comparaciones sin que se note a simple vista, así que el caso está fijado
contra un producto real verificado contra la ficha pública.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.adapters.compragamer import CompraGamerAdapter
from app.adapters.errors import NormalizationError
from app.adapters.types import RawListing, SearchQuery
from app.enums import WarrantyType

#: Producto real (id 18434), verificado el 2026-08-06 contra la ficha pública:
#: el sitio muestra "$ 2.882.400", que es `precioEspecial`.
ASUS_TUF = {
    "id_producto": 18434,
    "nombre": (
        'Notebook ASUS TUF Gaming F16 16" Intel Core i7 14650HX 16GB DDR5 '
        "SSD 512GB RTX 5060 8GB FREE DOS FX608JMR-RV024"
    ),
    "id_marca": 8,
    "id_subcategoria": 58,
    "precioLista": 3202667,
    "precioEspecial": 2882400,
    "precio_sin_impuestos": 2608507,
    "stock": 10,
    "vendible": 1,
}

MARCAS = [
    {"id": 8, "nombre": "ASUS", "marca_nombre_alias": "Asus", "garantia_oficial": 0,
     "garantia_meses_por_defecto": 36},
    {"id": 0, "nombre": "SIN DEFINIR", "marca_nombre_alias": "Sin definir",
     "garantia_oficial": 0, "garantia_meses_por_defecto": None},
]
CATEGORIAS = [{"id": 58, "nombre": "Notebooks"}]


def _adapter(**config) -> CompraGamerAdapter:
    adapter = CompraGamerAdapter(source_slug="compragamer", config=config)
    # Se precargan los archivos auxiliares para no tocar la red en los tests.
    adapter._brands = {int(m["id"]): m for m in MARCAS}
    adapter._categories = {int(c["id"]): c["nombre"] for c in CATEGORIAS}
    return adapter


def _normalized(**overrides):
    payload = {**ASUS_TUF, **overrides}
    raw = RawListing(
        source_slug="compragamer",
        external_id=str(payload["id_producto"]),
        payload=payload,
    )
    return _adapter().normalize(raw)


def test_price_is_in_whole_pesos_not_thousands_or_cents() -> None:
    """$ 2.882.400 en la web -> Decimal("2882400") en la base."""
    listing = _normalized()

    assert listing.price == Decimal("2882400")
    assert listing.currency == "ARS"
    # Sanidad de escala: una notebook gamer está entre cientos de miles y millones.
    assert Decimal("100000") < listing.price < Decimal("20000000")


def test_uses_the_displayed_price_not_the_crossed_out_one() -> None:
    """`precioEspecial` es el que muestra la tienda; `precioLista` es el tachado."""
    listing = _normalized()

    assert listing.price == Decimal(str(ASUS_TUF["precioEspecial"]))
    assert listing.price != Decimal(str(ASUS_TUF["precioLista"]))


def test_falls_back_to_list_price_when_there_is_no_special_one() -> None:
    listing = _normalized(precioEspecial=0)

    assert listing.price == Decimal(str(ASUS_TUF["precioLista"]))


def test_warranty_comes_from_the_brand() -> None:
    """La garantía es política del comercio por marca, no un campo del producto."""
    listing = _normalized()

    assert listing.warranty_months == 36
    assert listing.warranty_type == WarrantyType.VENDEDOR


def test_official_warranty_is_flagged_as_such() -> None:
    adapter = _adapter()
    adapter._brands[8] = {**MARCAS[0], "garantia_oficial": 1}
    raw = RawListing(source_slug="compragamer", external_id="18434", payload=ASUS_TUF)

    listing = adapter.normalize(raw)

    assert listing.warranty_type == WarrantyType.OFICIAL


def test_unknown_brand_leaves_warranty_empty() -> None:
    listing = _normalized(id_marca=0)

    assert listing.warranty_months is None
    assert listing.warranty_type == WarrantyType.UNKNOWN
    assert listing.product_hint.brand is None


def test_permalink_matches_the_public_url_format() -> None:
    """`/producto/{nombre_con_guiones_bajos}_{id}` — el formato que genera el sitio."""
    listing = _normalized()

    assert listing.permalink.startswith("https://compragamer.com/producto/")
    assert listing.permalink.endswith("_18434")
    assert "notebook_asus_tuf_gaming_f16" in listing.permalink


def test_brand_and_category_are_resolved_from_the_side_files() -> None:
    listing = _normalized()

    assert listing.product_hint.brand == "Asus"
    assert listing.product_hint.category == "Notebooks"
    assert listing.product_hint.catalog_product_id == "18434"


def test_item_without_price_is_rejected() -> None:
    with pytest.raises(NormalizationError):
        _normalized(precioEspecial=0, precioLista=0)


def test_item_without_name_is_rejected() -> None:
    with pytest.raises(NormalizationError):
        _normalized(nombre="")


# --- search: el filtrado es local sobre el catálogo completo -----------------


def _search(adapter: CompraGamerAdapter, catalog, term, **kwargs):
    adapter._catalog = catalog
    return list(adapter.search(SearchQuery(term=term, **kwargs)))


def test_search_matches_all_words_ignoring_case_and_accents() -> None:
    catalog = [
        ASUS_TUF,
        {**ASUS_TUF, "id_producto": 2, "nombre": "Monitor ASUS 24 pulgadas"},
        {**ASUS_TUF, "id_producto": 3, "nombre": "Notebook Lenovo IdeaPad"},
    ]

    found = _search(_adapter(), catalog, "NOTEBOOK asus")

    assert [r.external_id for r in found] == ["18434"]


def test_search_skips_items_without_stock() -> None:
    catalog = [
        {**ASUS_TUF, "id_producto": 10, "nombre": "Notebook sin stock", "stock": 0},
        {**ASUS_TUF, "id_producto": 11, "nombre": "Notebook no vendible", "vendible": 0},
        {**ASUS_TUF, "id_producto": 12, "nombre": "Notebook disponible"},
    ]

    found = _search(_adapter(), catalog, "notebook")

    assert [r.external_id for r in found] == ["12"]


def test_search_without_term_returns_the_whole_catalog() -> None:
    catalog = [ASUS_TUF, {**ASUS_TUF, "id_producto": 2, "nombre": "Otra cosa"}]

    found = _search(_adapter(), catalog, None)

    assert len(found) == 2


def test_search_respects_max_results() -> None:
    catalog = [{**ASUS_TUF, "id_producto": i, "nombre": f"Notebook {i}"} for i in range(10)]

    found = _search(_adapter(), catalog, "notebook", max_results=3)

    assert len(found) == 3

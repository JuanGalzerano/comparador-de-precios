"""Tests de VtexAdapter (app/adapters/vtex.py).

Sin red real: tráfico GET al endpoint IS interceptado con respx.

Cubre:
- búsqueda exitosa: normaliza productId, productName, sellingPrice, linkText → permalink, brand.
- item sin sellingPrice: lanza NormalizationError.
- item sin productName: lanza NormalizationError.
- installments: detecta la opción sin interés con más cuotas.
- max_results: corta antes de la segunda página.
- paginación: para cuando page*count >= recordsFiltered.
- 403: propaga BlockedBySource.
- 500: propaga SourceUnavailable.
- health_check OK y DOWN.
"""

from __future__ import annotations

from decimal import Decimal

import httpx
import pytest
import respx

from app.adapters.errors import BlockedBySource, NormalizationError, SourceUnavailable
from app.adapters.vtex import VtexAdapter, _IS_PATH
from app.adapters.types import RawListing, SearchQuery
from app.enums import ItemCondition, WarrantyType

BASE = "https://www.cetrogar.com.ar"
IS_URL = BASE + _IS_PATH


def _adapter(**overrides) -> VtexAdapter:
    cfg = {"max_retries": 1, "timeout_seconds": 5.0, "base_url": BASE}
    cfg.update(overrides)
    return VtexAdapter(source_slug="cetrogar", config=cfg)


def _product(
    product_id: str = "12345",
    name: str = "iPhone 13 128GB",
    brand: str = "Apple",
    price: int = 1_399_999,
    link_text: str | None = None,
    installments: list[dict] | None = None,
) -> dict:
    sellers: list[dict] = []
    if installments is not None:
        sellers = [{"commertialOffer": {"Installments": installments}}]
    return {
        "productId": product_id,
        "productName": name,
        "brand": brand,
        "linkText": link_text or f"iphone-13-128gb-{product_id}",
        "priceRange": {
            "sellingPrice": {"highPrice": price, "lowPrice": price},
            "listPrice": {"highPrice": price + 100_000, "lowPrice": price + 100_000},
        },
        "items": [{"sellers": sellers}] if sellers else [],
    }


def _is_ok(products: list[dict], records_filtered: int | None = None) -> dict:
    return {
        "products": products,
        "recordsFiltered": records_filtered if records_filtered is not None else len(products),
    }


# ---------------------------------------------------------------------------
# search(): caso feliz
# ---------------------------------------------------------------------------


@respx.mock
def test_search_normalizes_correctly():
    respx.get(IS_URL).mock(return_value=httpx.Response(200, json=_is_ok([_product("99991111")])))

    adapter = _adapter()
    raws = list(adapter.search(SearchQuery(term="iphone 13", enrich=False)))

    assert len(raws) == 1
    raw = raws[0]
    assert raw.external_id == "99991111"

    listing = adapter.normalize(raw)
    assert listing.source_slug == "cetrogar"
    assert listing.external_id == "99991111"
    assert listing.title == "iPhone 13 128GB"
    assert listing.price == Decimal("1399999")
    assert listing.currency == "ARS"
    assert listing.permalink == f"{BASE}/iphone-13-128gb-99991111/p"
    assert listing.product_hint.brand == "Apple"
    assert listing.condition == ItemCondition.UNKNOWN
    assert listing.shipping_cost is None
    assert listing.rating is None
    assert listing.warranty_type == WarrantyType.UNKNOWN
    assert listing.seller_name is None


# ---------------------------------------------------------------------------
# normalize(): installments sin interés
# ---------------------------------------------------------------------------


def test_normalize_extracts_best_free_installment():
    installments = [
        {"NumberOfInstallments": 1, "Value": 1_399_999, "InterestRate": 0,
         "TotalValuePlusInterestRate": 1_399_999},
        {"NumberOfInstallments": 3, "Value": 466_666, "InterestRate": 0,
         "TotalValuePlusInterestRate": 1_399_999},
        {"NumberOfInstallments": 6, "Value": 300_000, "InterestRate": 5.5,
         "TotalValuePlusInterestRate": 1_800_000},
    ]
    raw = RawListing(
        source_slug="cetrogar",
        external_id="X1",
        payload=_product("X1", installments=installments),
    )
    listing = _adapter().normalize(raw)
    assert listing.installments_qty == 3
    assert listing.installments_amount == Decimal("466666")
    assert listing.interest_free is True


# ---------------------------------------------------------------------------
# normalize(): sin sellingPrice → NormalizationError
# ---------------------------------------------------------------------------


def test_normalize_raises_without_price():
    p = _product("BAD1")
    p["priceRange"]["sellingPrice"] = {}
    raw = RawListing(source_slug="cetrogar", external_id="BAD1", payload=p)
    with pytest.raises(NormalizationError, match="sellingPrice"):
        _adapter().normalize(raw)


# ---------------------------------------------------------------------------
# normalize(): sin productName → NormalizationError
# ---------------------------------------------------------------------------


def test_normalize_raises_without_name():
    p = _product("BAD2")
    p["productName"] = ""
    raw = RawListing(source_slug="cetrogar", external_id="BAD2", payload=p)
    with pytest.raises(NormalizationError, match="productName"):
        _adapter().normalize(raw)


# ---------------------------------------------------------------------------
# normalize(): sin brand → product_hint.brand es None
# ---------------------------------------------------------------------------


def test_normalize_tolerates_missing_brand():
    p = _product("OKK1")
    p["brand"] = None
    raw = RawListing(source_slug="cetrogar", external_id="OKK1", payload=p)
    listing = _adapter().normalize(raw)
    assert listing.product_hint.brand is None


# ---------------------------------------------------------------------------
# search(): max_results corta antes de segunda página
# ---------------------------------------------------------------------------


@respx.mock
def test_search_respects_max_results():
    call_count = 0

    def handler(request):
        nonlocal call_count
        call_count += 1
        return httpx.Response(
            200,
            json=_is_ok([_product("A"), _product("B"), _product("C")], records_filtered=100),
        )

    respx.get(IS_URL).mock(side_effect=handler)

    raws = list(_adapter().search(SearchQuery(term="iphone", enrich=False, max_results=2)))
    assert len(raws) == 2
    assert call_count == 1


# ---------------------------------------------------------------------------
# search(): para cuando page*count >= recordsFiltered
# ---------------------------------------------------------------------------


@respx.mock
def test_search_stops_when_exhausted():
    responses = [
        httpx.Response(200, json=_is_ok([_product("P1"), _product("P2")], records_filtered=2)),
    ]
    respx.get(IS_URL).mock(side_effect=responses)

    raws = list(_adapter().search(SearchQuery(term="test", enrich=False, page_size=48)))
    assert len(raws) == 2


# ---------------------------------------------------------------------------
# search(): 403 → BlockedBySource
# ---------------------------------------------------------------------------


@respx.mock
def test_search_raises_blocked_on_403():
    respx.get(IS_URL).mock(return_value=httpx.Response(403))
    with pytest.raises(BlockedBySource):
        list(_adapter().search(SearchQuery(term="x", enrich=False)))


# ---------------------------------------------------------------------------
# search(): 500 → SourceUnavailable
# ---------------------------------------------------------------------------


@respx.mock
def test_search_raises_on_500():
    respx.get(IS_URL).mock(return_value=httpx.Response(500))
    with pytest.raises(SourceUnavailable):
        list(_adapter().search(SearchQuery(term="x", enrich=False)))


# ---------------------------------------------------------------------------
# health_check(): OK
# ---------------------------------------------------------------------------


@respx.mock
def test_health_check_ok():
    respx.get(IS_URL).mock(
        return_value=httpx.Response(200, json=_is_ok([_product()]))
    )
    status = _adapter().health_check()
    assert status.ok


# ---------------------------------------------------------------------------
# health_check(): DOWN en 500
# ---------------------------------------------------------------------------


@respx.mock
def test_health_check_down_on_500():
    respx.get(IS_URL).mock(return_value=httpx.Response(500))
    status = _adapter().health_check()
    assert not status.ok

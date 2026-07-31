"""Tests de FravegaAdapter (app/adapters/fravega.py).

Sin red real: todo el tráfico POST a /api/v2 interceptado con respx.

Cubre:
- búsqueda exitosa: normaliza code, title, salePrice, slug → permalink, brand.
- item sin salePrice: lanza NormalizationError.
- item sin title: lanza NormalizationError.
- max_results: corta antes de la segunda página.
- paginación: para cuando offset >= total.
- error GraphQL (campo "errors" en el body): propaga SourceUnavailable.
- 403: propaga BlockedBySource.
- health_check OK y DOWN.
"""

from __future__ import annotations

from decimal import Decimal

import httpx
import pytest
import respx

from app.adapters.errors import BlockedBySource, NormalizationError, SourceUnavailable
from app.adapters.fravega import FravegaAdapter
from app.adapters.types import RawListing, SearchQuery
from app.enums import ItemCondition, WarrantyType

GQL_URL = "https://www.fravega.com/api/v2"


def _adapter(**overrides) -> FravegaAdapter:
    cfg = {"max_retries": 1, "timeout_seconds": 5.0}
    cfg.update(overrides)
    return FravegaAdapter(source_slug="fravega", config=cfg)


def _sku(code: str = "12345678", **overrides) -> dict:
    item = {
        "code": code,
        "item": {
            "title": f"iPhone 13 128GB ({code})",
            "slug": f"iphone-13-128gb-{code}",
            "brand": {"name": "Apple"},
        },
        "pricing": {"salePrice": 1_399_999, "listPrice": 2_045_250, "discount": 32},
        "seller": {"commercialName": "ShopWide"},
    }
    item.update(overrides)
    return item


def _gql_ok(results: list[dict], total: int | None = None) -> dict:
    return {"data": {"items": {"total": total or len(results), "results": results}}}


# ---------------------------------------------------------------------------
# search(): caso feliz
# ---------------------------------------------------------------------------


@respx.mock
def test_search_normalizes_correctly():
    respx.post(GQL_URL).mock(return_value=httpx.Response(200, json=_gql_ok([_sku("99991111")])))

    adapter = _adapter()
    raws = list(adapter.search(SearchQuery(term="iphone 13", enrich=False)))

    assert len(raws) == 1
    raw = raws[0]
    assert raw.external_id == "99991111"

    listing = adapter.normalize(raw)
    assert listing.source_slug == "fravega"
    assert listing.external_id == "99991111"
    assert listing.title == "iPhone 13 128GB (99991111)"
    assert listing.price == Decimal("1399999")
    assert listing.currency == "ARS"
    assert listing.permalink == "https://www.fravega.com/producto/iphone-13-128gb-99991111/99991111/"
    assert listing.seller_name == "ShopWide"
    assert listing.product_hint.brand == "Apple"
    assert listing.condition == ItemCondition.UNKNOWN
    assert listing.shipping_cost is None
    assert listing.rating is None
    assert listing.warranty_type == WarrantyType.UNKNOWN


# ---------------------------------------------------------------------------
# search(): max_results detiene antes de segunda página
# ---------------------------------------------------------------------------


@respx.mock
def test_search_respects_max_results():
    call_count = 0

    def handler(request):
        nonlocal call_count
        call_count += 1
        return httpx.Response(200, json=_gql_ok([_sku("A"), _sku("B"), _sku("C")], total=100))

    respx.post(GQL_URL).mock(side_effect=handler)

    adapter = _adapter()
    raws = list(adapter.search(SearchQuery(term="iphone", enrich=False, max_results=2)))

    assert len(raws) == 2
    assert call_count == 1  # no segunda página


# ---------------------------------------------------------------------------
# search(): paginación para cuando offset >= total
# ---------------------------------------------------------------------------


@respx.mock
def test_search_stops_when_exhausted():
    responses = [
        httpx.Response(200, json=_gql_ok([_sku("P1"), _sku("P2")], total=2)),
    ]
    respx.post(GQL_URL).mock(side_effect=responses)

    adapter = _adapter()
    raws = list(adapter.search(SearchQuery(term="test", enrich=False, page_size=48)))
    assert len(raws) == 2


# ---------------------------------------------------------------------------
# search(): error GraphQL → SourceUnavailable
# ---------------------------------------------------------------------------


@respx.mock
def test_search_raises_on_graphql_error():
    respx.post(GQL_URL).mock(
        return_value=httpx.Response(
            200, json={"errors": [{"message": "Field 'items' not found"}]}
        )
    )
    with pytest.raises(SourceUnavailable, match="GraphQL error"):
        list(_adapter().search(SearchQuery(term="x", enrich=False)))


# ---------------------------------------------------------------------------
# search(): 403 → BlockedBySource
# ---------------------------------------------------------------------------


@respx.mock
def test_search_raises_blocked_on_403():
    respx.post(GQL_URL).mock(return_value=httpx.Response(403))
    with pytest.raises(BlockedBySource):
        list(_adapter().search(SearchQuery(term="x", enrich=False)))


# ---------------------------------------------------------------------------
# normalize(): sin salePrice → NormalizationError
# ---------------------------------------------------------------------------


def test_normalize_raises_without_price():
    sku = _sku("BAD1")
    sku["pricing"] = {}
    raw = RawListing(source_slug="fravega", external_id="BAD1", payload=sku)
    with pytest.raises(NormalizationError, match="sin salePrice"):
        _adapter().normalize(raw)


# ---------------------------------------------------------------------------
# normalize(): sin title → NormalizationError
# ---------------------------------------------------------------------------


def test_normalize_raises_without_title():
    sku = _sku("BAD2")
    sku["item"]["title"] = ""
    raw = RawListing(source_slug="fravega", external_id="BAD2", payload=sku)
    with pytest.raises(NormalizationError, match="sin title"):
        _adapter().normalize(raw)


# ---------------------------------------------------------------------------
# normalize(): sin brand → product_hint.brand es None (no rompe)
# ---------------------------------------------------------------------------


def test_normalize_tolerates_missing_brand():
    sku = _sku("OKK1")
    sku["item"]["brand"] = None
    raw = RawListing(source_slug="fravega", external_id="OKK1", payload=sku)
    listing = _adapter().normalize(raw)
    assert listing.product_hint.brand is None


# ---------------------------------------------------------------------------
# normalize(): permalink usa base_url del config
# ---------------------------------------------------------------------------


def test_normalize_permalink_uses_config_base_url():
    sku = _sku("TSTSKU")
    raw = RawListing(source_slug="fravega", external_id="TSTSKU", payload=sku)
    listing = _adapter(base_url="https://www.fravega.com").normalize(raw)
    assert listing.permalink == "https://www.fravega.com/producto/iphone-13-128gb-TSTSKU/TSTSKU/"


# ---------------------------------------------------------------------------
# health_check(): OK cuando GraphQL devuelve items
# ---------------------------------------------------------------------------


@respx.mock
def test_health_check_ok():
    respx.post(GQL_URL).mock(return_value=httpx.Response(200, json=_gql_ok([_sku()])))
    status = _adapter().health_check()
    assert status.ok


# ---------------------------------------------------------------------------
# health_check(): DOWN cuando el endpoint no responde
# ---------------------------------------------------------------------------


@respx.mock
def test_health_check_down_on_500():
    respx.post(GQL_URL).mock(return_value=httpx.Response(500))
    status = _adapter().health_check()
    assert not status.ok

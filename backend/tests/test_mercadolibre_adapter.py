"""Tests de `MercadoLibreAdapter` (`app/adapters/mercadolibre.py`).

Nada de red real: todo el trafico HTTP se intercepta con `respx`. Cubre:

- una busqueda exitosa que normaliza correctamente (con enrichment de seller/reviews);
- un item sin reviews (`/reviews/item/:id` en 404) no rompe, normaliza rating=None;
- un item con atributo de garantia ausente/malformado cae a un default sano
  (`warranty_months=None`, `WarrantyType.UNKNOWN`), y el caso `"Sin garantia"` a
  `WarrantyType.SIN`/`warranty_months=0`;
- `fetch_by_ids` batchea correctamente en el limite de 20 (dos requests para 21 ids).
"""

from __future__ import annotations

from decimal import Decimal

import httpx
import pytest
import respx

from app.adapters.errors import NormalizationError
from app.adapters.mercadolibre import MercadoLibreAdapter
from app.adapters.types import RawListing, RefreshRequest, SearchQuery
from app.enums import ItemCondition, WarrantyType

BASE_URL = "https://api.mercadolibre.com"


def _adapter(**config_overrides) -> MercadoLibreAdapter:
    config = {"max_retries": 1, "timeout_seconds": 5.0}
    config.update(config_overrides)
    return MercadoLibreAdapter(source_slug="mercadolibre", config=config)


def _search_item(item_id: str, **overrides) -> dict:
    item = {
        "id": item_id,
        "title": f"Producto {item_id}",
        "permalink": f"https://articulo.mercadolibre.com.ar/{item_id}",
        "condition": "new",
        "price": 100000,
        "currency_id": "ARS",
        "official_store_id": None,
        "catalog_product_id": "MLA123",
        "shipping": {"free_shipping": True, "logistic_type": "fulfillment", "tags": []},
        "installments": {"quantity": 12, "amount": 9000, "rate": 0},
        "seller": {"id": 555, "nickname": "TiendaTest"},
        "attributes": [
            {"id": "WARRANTY_TYPE", "value_name": "Garantía de fábrica"},
            {"id": "WARRANTY_TIME", "value_name": "12 meses"},
            {"id": "BRAND", "value_name": "Acme"},
            {"id": "MODEL", "value_name": "X100"},
        ],
        "warranty": "Garantía de fábrica: 12 meses",
    }
    item.update(overrides)
    return item


def _user_payload(seller_id: int = 555, power_status: str | None = "gold", sales: int = 4200) -> dict:
    return {
        "id": seller_id,
        "nickname": "TiendaTest",
        "seller_reputation": {
            "level_id": "5_green",
            "power_seller_status": power_status,
            "transactions": {"total": sales},
        },
    }


def _reviews_payload(rating_average: float = 4.6, total: int = 320) -> dict:
    return {"rating_average": rating_average, "total": total}


# ---------------------------------------------------------------------------
# search(): busqueda exitosa con enrichment
# ---------------------------------------------------------------------------


@respx.mock
def test_search_normalizes_successfully_with_enrichment():
    search_route = respx.get(f"{BASE_URL}/sites/MLA/search").mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [_search_item("MLA-1")],
                "paging": {"total": 1, "offset": 0, "limit": 50},
            },
        )
    )
    items_route = respx.get(f"{BASE_URL}/items", params={"ids": "MLA-1"}).mock(
        return_value=httpx.Response(
            200, json=[{"code": 200, "body": _search_item("MLA-1")}]
        )
    )
    user_route = respx.get(f"{BASE_URL}/users/555").mock(
        return_value=httpx.Response(200, json=_user_payload())
    )
    reviews_route = respx.get(f"{BASE_URL}/reviews/item/MLA-1").mock(
        return_value=httpx.Response(200, json=_reviews_payload())
    )

    adapter = _adapter()
    query = SearchQuery(term="iphone", enrich=True, page_size=50)
    raws = list(adapter.search(query))

    assert search_route.called
    assert items_route.called
    assert user_route.called
    assert reviews_route.called
    assert len(raws) == 1

    listing = adapter.normalize(raws[0])
    assert listing.source_slug == "mercadolibre"
    assert listing.external_id == "MLA-1"
    assert listing.title == "Producto MLA-1"
    assert listing.condition == ItemCondition.NEW
    assert listing.price == Decimal("100000")
    assert listing.shipping_cost == Decimal("0")
    assert listing.fulfillment is True
    assert listing.interest_free is True
    assert listing.seller_level == "gold"
    assert listing.seller_sales == 4200
    assert listing.rating == Decimal("4.6")
    assert listing.reviews_count == 320
    assert listing.warranty_months == 12
    assert listing.warranty_type == WarrantyType.OFICIAL
    assert listing.product_hint.catalog_product_id == "MLA123"
    assert listing.product_hint.brand == "Acme"
    assert listing.product_hint.model == "X100"


@respx.mock
def test_search_respects_max_results_and_stops_paginating():
    respx.get(f"{BASE_URL}/sites/MLA/search").mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [_search_item("MLA-1"), _search_item("MLA-2")],
                "paging": {"total": 2, "offset": 0, "limit": 50},
            },
        )
    )
    adapter = _adapter()
    query = SearchQuery(term="iphone", enrich=False, max_results=1)
    raws = list(adapter.search(query))
    assert len(raws) == 1
    assert raws[0].external_id == "MLA-1"
    assert raws[0].related == {}


# ---------------------------------------------------------------------------
# Item sin reviews: no debe romper, rating/reviews quedan en None
# ---------------------------------------------------------------------------


@respx.mock
def test_missing_reviews_does_not_crash_and_normalizes_to_none():
    respx.get(f"{BASE_URL}/sites/MLA/search").mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [_search_item("MLA-2")],
                "paging": {"total": 1, "offset": 0, "limit": 50},
            },
        )
    )
    respx.get(f"{BASE_URL}/items", params={"ids": "MLA-2"}).mock(
        return_value=httpx.Response(
            200, json=[{"code": 200, "body": _search_item("MLA-2")}]
        )
    )
    respx.get(f"{BASE_URL}/users/555").mock(
        return_value=httpx.Response(200, json=_user_payload())
    )
    # ML no siempre tiene reviews para un item: 404 explicito.
    respx.get(f"{BASE_URL}/reviews/item/MLA-2").mock(return_value=httpx.Response(404))

    adapter = _adapter()
    query = SearchQuery(term="iphone", enrich=True)
    raws = list(adapter.search(query))
    listing = adapter.normalize(raws[0])

    assert listing.rating is None
    assert listing.reviews_count is None


# ---------------------------------------------------------------------------
# Garantia: ausente/malformada -> default sano; "Sin garantia" -> SIN
# ---------------------------------------------------------------------------


def _raw_with_item(item: dict) -> RawListing:
    return RawListing(source_slug="mercadolibre", external_id=item["id"], payload=item)


def test_normalize_defaults_sanely_when_warranty_attribute_missing():
    item = _search_item("MLA-3", attributes=[], warranty=None)
    adapter = _adapter()
    listing = adapter.normalize(_raw_with_item(item))
    assert listing.warranty_months is None
    assert listing.warranty_type == WarrantyType.UNKNOWN


def test_normalize_parses_sin_garantia_text():
    item = _search_item(
        "MLA-4",
        attributes=[],
        warranty="Sin garantía",
    )
    adapter = _adapter()
    listing = adapter.normalize(_raw_with_item(item))
    assert listing.warranty_type == WarrantyType.SIN
    assert listing.warranty_months == 0


def test_normalize_parses_dias_and_vendedor_warranty():
    item = _search_item(
        "MLA-5",
        attributes=[],
        warranty="Garantía del vendedor: 90 días",
    )
    adapter = _adapter()
    listing = adapter.normalize(_raw_with_item(item))
    assert listing.warranty_type == WarrantyType.VENDEDOR
    assert listing.warranty_months == 3  # 90 dias -> round(90/30) = 3 meses


def test_normalize_raises_normalization_error_without_price():
    item = _search_item("MLA-6")
    del item["price"]
    adapter = _adapter()
    with pytest.raises(NormalizationError):
        adapter.normalize(_raw_with_item(item))


# ---------------------------------------------------------------------------
# fetch_by_ids: batching en el limite de 20
# ---------------------------------------------------------------------------


@respx.mock
def test_fetch_by_ids_batches_at_20_item_boundary():
    ids = [f"MLA-{i}" for i in range(21)]  # 21 ids -> 2 lotes: 20 + 1

    def _items_response(request: httpx.Request) -> httpx.Response:
        requested_ids = request.url.params["ids"].split(",")
        assert len(requested_ids) <= 20
        body = [
            {"code": 200, "body": _search_item(item_id)} for item_id in requested_ids
        ]
        return httpx.Response(200, json=body)

    route = respx.get(f"{BASE_URL}/items").mock(side_effect=_items_response)

    adapter = _adapter()
    request = RefreshRequest(external_ids=ids, enrich=False)
    raws = list(adapter.fetch_by_ids(request))

    assert route.call_count == 2
    first_call_ids = route.calls[0].request.url.params["ids"].split(",")
    second_call_ids = route.calls[1].request.url.params["ids"].split(",")
    assert len(first_call_ids) == 20
    assert len(second_call_ids) == 1
    assert {raw.external_id for raw in raws} == set(ids)
    # enrich=False (default de refresh): no debe haber pegado a /users ni /reviews.
    assert all(raw.related == {} for raw in raws)


@respx.mock
def test_fetch_by_ids_skips_ids_not_found():
    ids = ["MLA-OK", "MLA-MISSING"]
    respx.get(f"{BASE_URL}/items").mock(
        return_value=httpx.Response(
            200,
            json=[
                {"code": 200, "body": _search_item("MLA-OK")},
                {"code": 404, "body": {"error": "not_found"}},
            ],
        )
    )
    adapter = _adapter()
    request = RefreshRequest(external_ids=ids, enrich=False)
    raws = list(adapter.fetch_by_ids(request))
    assert [raw.external_id for raw in raws] == ["MLA-OK"]


# ---------------------------------------------------------------------------
# health_check
# ---------------------------------------------------------------------------


@respx.mock
def test_health_check_ok():
    respx.get(f"{BASE_URL}/sites/MLA").mock(return_value=httpx.Response(200, json={}))
    adapter = _adapter()
    status = adapter.health_check()
    assert status.ok


@respx.mock
def test_health_check_blocked_on_403():
    respx.get(f"{BASE_URL}/sites/MLA").mock(return_value=httpx.Response(403))
    adapter = _adapter()
    status = adapter.health_check()
    assert status.state.value == "blocked"


@respx.mock
def test_health_check_down_on_connection_error():
    respx.get(f"{BASE_URL}/sites/MLA").mock(side_effect=httpx.ConnectError("boom"))
    adapter = _adapter()
    status = adapter.health_check()
    assert status.state.value == "down"

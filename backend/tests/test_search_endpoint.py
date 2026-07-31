"""Tests de `GET /search` (`app/api/routers/search.py`).

Contra el fixture sembrado en `tests/conftest.py`: cluster `iphone` (4 publicaciones,
categoria `celulares`) y cluster `remera` (1 publicacion, categoria `indumentaria`).
"""

from __future__ import annotations

from decimal import Decimal


def test_search_without_filters_returns_both_clusters_ordered_by_min_final_price(
    client, seeded_db
):
    resp = client.get("/search")
    assert resp.status_code == 200
    body = resp.json()

    assert body["total"] == 2
    assert body["page"] == 1
    assert body["page_size"] == 20
    assert [item["canonical_title"] for item in body["items"]] == [
        "Remera Nike Sportswear Club — hombre",  # final=42999, mas barato
        "Apple iPhone 13 128 GB",  # final minimo = 690000+12000=702000
    ]

    remera, iphone = body["items"]
    assert remera["listing_count"] == 1
    assert Decimal(str(remera["min_final_price"])) == Decimal("42999")
    assert remera["catalog_product_id"] is None

    assert iphone["listing_count"] == 4
    assert Decimal(str(iphone["min_final_price"])) == Decimal("702000")
    assert Decimal(str(iphone["max_final_price"])) == Decimal("1049000")
    assert iphone["catalog_product_id"] == "MLA22811322"
    # best_score tiene que ser un score valido (0-100) de scoreOf().
    assert 0 <= iphone["best_score"] <= 100


def test_search_pagination(client, seeded_db):
    resp = client.get("/search", params={"page": 1, "page_size": 1})
    body = resp.json()
    assert body["total"] == 2
    assert body["page"] == 1
    assert body["page_size"] == 1
    assert len(body["items"]) == 1
    assert body["items"][0]["canonical_title"] == "Remera Nike Sportswear Club — hombre"

    resp2 = client.get("/search", params={"page": 2, "page_size": 1})
    body2 = resp2.json()
    assert len(body2["items"]) == 1
    assert body2["items"][0]["canonical_title"] == "Apple iPhone 13 128 GB"

    resp3 = client.get("/search", params={"page": 3, "page_size": 1})
    assert resp3.json()["items"] == []


def test_search_filters_by_category(client, seeded_db):
    resp = client.get("/search", params={"category": "celulares"})
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["canonical_title"] == "Apple iPhone 13 128 GB"

    # case-insensitive
    resp2 = client.get("/search", params={"category": "CELULARES"})
    assert resp2.json()["total"] == 1


def test_search_filters_by_condition_only_counts_matching_listings(client, seeded_db):
    resp = client.get("/search", params={"condition": "used"})
    body = resp.json()
    assert body["total"] == 1
    iphone = body["items"][0]
    # Solo MLA-1904 es 'used': el resumen del cluster tiene que reflejar SOLO esa
    # publicacion, no las 4 del cluster completo.
    assert iphone["listing_count"] == 1
    assert Decimal(str(iphone["min_final_price"])) == Decimal("702000")
    assert Decimal(str(iphone["max_final_price"])) == Decimal("702000")


def test_search_filters_by_free_text_query(client, seeded_db):
    resp = client.get("/search", params={"q": "Nike"})
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["canonical_title"] == "Remera Nike Sportswear Club — hombre"

    resp2 = client.get("/search", params={"q": "no existe ningun producto asi"})
    assert resp2.json()["total"] == 0
    assert resp2.json()["items"] == []


def test_search_q_matches_listing_title_not_just_product_title(client, seeded_db):
    # "sellado" solo aparece en el titulo de la publicacion MLA-8821, no en
    # canonical_title/brand/model del producto.
    resp = client.get("/search", params={"q": "sellado"})
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["canonical_title"] == "Apple iPhone 13 128 GB"
    assert body["items"][0]["listing_count"] == 1


def test_search_empty_db_returns_empty_page(client, db_session):
    resp = client.get("/search")
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"items": [], "page": 1, "page_size": 20, "total": 0}

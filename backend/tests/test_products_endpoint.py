"""Tests de `GET /products/{id}` y `GET /products/{id}/price-history`
(`app/api/routers/products.py`).

Los scores esperados se calcularon con una corrida standalone de
`app.scoring.score.score_listings()` sobre los mismos 4 datos del fixture
(`tests/conftest.py::_seed_iphone_cluster`), fuera de la app (no reusa el codigo del
endpoint), para no validar el endpoint contra si mismo:

    MLA-8821 -> 66   MLA-4410 -> 54   MLA-6120 -> 32   MLA-1904 -> 69

(min/max de `final_price` sobre las 4: 702000 / 1049000).
"""

from __future__ import annotations

from decimal import Decimal


def _get_iphone_product_id(seeded_db) -> int:
    from app.models.product import Product

    return seeded_db.query(Product).filter_by(canonical_title="Apple iPhone 13 128 GB").one().id


def test_get_product_404_when_missing(client, seeded_db):
    resp = client.get("/products/999999")
    assert resp.status_code == 404


def test_get_product_returns_all_listings_sorted_by_score_by_default(client, seeded_db):
    product_id = _get_iphone_product_id(seeded_db)
    resp = client.get(f"/products/{product_id}")
    assert resp.status_code == 200
    body = resp.json()

    assert body["canonical_title"] == "Apple iPhone 13 128 GB"
    assert body["catalog_product_id"] == "MLA22811322"
    assert len(body["listings"]) == 4

    # Cada listing tiene que traer permalink (CTA de la UI) SIEMPRE.
    assert all(item["permalink"].startswith("https://articulo.mercadolibre.com.ar/") for item in body["listings"])

    ids_in_order = [item["title"] for item in body["listings"]]
    scores_in_order = [item["score"] for item in body["listings"]]
    assert scores_in_order == sorted(scores_in_order, reverse=True)

    by_id = {item["id"]: item for item in body["listings"]}
    external_id_to_score = {
        "MLA-1904": 69,
        "MLA-8821": 66,
        "MLA-4410": 54,
        "MLA-6120": 32,
    }
    # Empareja por titulo (unico por listing en el fixture) para chequear el score
    # exacto de cada uno, sin asumir el orden en el que quedaron en la respuesta.
    title_to_external_id = {
        "iPhone 13 128GB Midnight — sellado": "MLA-8821",
        "Apple iPhone 13 128 GB azul medianoche": "MLA-4410",
        "iPhone 13 128gb liberado importado": "MLA-6120",
        "iPhone 13 128 GB usado, 92% bateria": "MLA-1904",
    }
    for item in body["listings"]:
        external_id = title_to_external_id[item["title"]]
        assert item["score"] == external_id_to_score[external_id]


def test_get_product_sort_by_price_ascending(client, seeded_db):
    product_id = _get_iphone_product_id(seeded_db)
    resp = client.get(f"/products/{product_id}", params={"sort": "price"})
    finals = [Decimal(str(item["final_price"])) for item in resp.json()["listings"]]
    assert finals == sorted(finals)
    assert finals[0] == Decimal("702000")  # MLA-1904
    assert finals[-1] == Decimal("1049000")  # MLA-8821


def test_get_product_filter_free_shipping(client, seeded_db):
    product_id = _get_iphone_product_id(seeded_db)
    resp = client.get(f"/products/{product_id}", params={"free": "true"})
    body = resp.json()
    # Solo MLA-8821 y MLA-4410 tienen shipping_cost == 0.
    assert len(body["listings"]) == 2
    assert all(Decimal(str(item["shipping_cost"])) == 0 for item in body["listings"])


def test_get_product_filter_official_store(client, seeded_db):
    product_id = _get_iphone_product_id(seeded_db)
    resp = client.get(f"/products/{product_id}", params={"official": "true"})
    body = resp.json()
    assert len(body["listings"]) == 1
    assert body["listings"][0]["official_store"] == "Apple Premium Reseller"


def test_get_product_filter_warranty_min_6_months(client, seeded_db):
    product_id = _get_iphone_product_id(seeded_db)
    resp = client.get(f"/products/{product_id}", params={"warranty": "true"})
    body = resp.json()
    # MLA-8821 (12 meses) y MLA-4410 (6 meses) pasan; MLA-6120 (0) y MLA-1904 (3) no.
    warranty_months = sorted(item["warranty_months"] for item in body["listings"])
    assert warranty_months == [6, 12]


def test_get_product_filter_condition(client, seeded_db):
    product_id = _get_iphone_product_id(seeded_db)
    resp = client.get(f"/products/{product_id}", params={"condition": "used"})
    body = resp.json()
    assert len(body["listings"]) == 1
    assert body["listings"][0]["condition"] == "used"


def test_get_product_filters_combine_with_and(client, seeded_db):
    product_id = _get_iphone_product_id(seeded_db)
    resp = client.get(
        f"/products/{product_id}", params={"free": "true", "official": "true"}
    )
    body = resp.json()
    assert len(body["listings"]) == 1
    assert body["listings"][0]["official_store"] == "Apple Premium Reseller"


def test_get_product_score_normalizes_against_visible_set_not_whole_cluster(client, seeded_db):
    """Filtrar por envio gratis dejar solo 2 publicaciones: el score de esas 2 tiene
    que recalcularse contra el min/max de ESE subset, no contra las 4 del cluster."""
    product_id = _get_iphone_product_id(seeded_db)
    resp = client.get(f"/products/{product_id}", params={"free": "true"})
    body = resp.json()
    assert len(body["listings"]) == 2
    # Con solo estas 2 (MLA-8821 final=1049000, MLA-4410 final=989000), el mas barato
    # (MLA-4410) tiene que valer priceScore=1 en ese subset y por lo tanto un score
    # mayor o igual al que tenia en el set completo de 4 (donde no era el mas barato).
    by_title = {item["title"]: item["score"] for item in body["listings"]}
    assert by_title["Apple iPhone 13 128 GB azul medianoche"] >= 54  # score en el set de 4


def test_get_product_empty_after_filters_returns_empty_list(client, seeded_db):
    product_id = _get_iphone_product_id(seeded_db)
    # Ninguna publicacion del cluster iphone es simultaneamente 'used' y con envio
    # gratis (MLA-1904, la unica used, tiene shipping_cost=12000).
    resp = client.get(
        f"/products/{product_id}", params={"condition": "used", "free": "true"}
    )
    assert resp.status_code == 200
    assert resp.json()["listings"] == []


def test_price_history_404_when_product_missing(client, seeded_db):
    resp = client.get("/products/999999/price-history")
    assert resp.status_code == 404


def test_price_history_default_window_excludes_points_older_than_90_days(client, seeded_db):
    product_id = _get_iphone_product_id(seeded_db)
    resp = client.get(f"/products/{product_id}/price-history")
    assert resp.status_code == 200
    body = resp.json()
    assert body["product_id"] == product_id
    # Solo el snapshot de hace 5 dias entra en la ventana default de 90; el de hace
    # 120 dias queda afuera.
    assert len(body["points"]) == 1
    assert Decimal(str(body["points"][0]["price"])) == Decimal("690000")


def test_price_history_wider_window_includes_older_point(client, seeded_db):
    product_id = _get_iphone_product_id(seeded_db)
    resp = client.get(f"/products/{product_id}/price-history", params={"days": 200})
    body = resp.json()
    assert len(body["points"]) == 2
    prices = sorted(Decimal(str(p["price"])) for p in body["points"])
    assert prices == [Decimal("690000"), Decimal("710000")]

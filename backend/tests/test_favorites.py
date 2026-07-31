"""Tests de `/me/favorites` (`app/api/routers/favorites.py`).

Reusa el fixture sembrado de `tests/conftest.py` (cluster `iphone`, 4 publicaciones;
cluster `remera`, 1 publicacion) y se autentica registrando un usuario nuevo con el mismo
`client` — las cookies viajan solas entre requests del mismo test.
"""

from __future__ import annotations

from app.models.product import Product
from app.models.saved_product import SavedProduct

_EMAIL = "fan@example.com"
_PASSWORD = "supersecret1"


def _register(client):
    resp = client.post(
        "/auth/register", json={"email": _EMAIL, "password": _PASSWORD, "display_name": "Fan"}
    )
    assert resp.status_code == 201
    return resp.json()


def _iphone_product(seeded_db) -> Product:
    product = (
        seeded_db.query(Product).filter_by(canonical_title="Apple iPhone 13 128 GB").first()
    )
    assert product is not None
    return product


def test_list_favorites_requires_auth(client, seeded_db):
    resp = client.get("/me/favorites")
    assert resp.status_code == 401


def test_favorite_ids_requires_auth(client, seeded_db):
    resp = client.get("/me/favorites/ids")
    assert resp.status_code == 401


def test_put_favorite_twice_is_idempotent_and_204_both_times(client, seeded_db):
    _register(client)
    product = _iphone_product(seeded_db)

    first = client.put(f"/me/favorites/{product.id}")
    second = client.put(f"/me/favorites/{product.id}")
    assert first.status_code == 204
    assert second.status_code == 204

    rows = seeded_db.query(SavedProduct).filter_by(product_id=product.id).all()
    assert len(rows) == 1


def test_put_favorite_unknown_product_is_404(client, seeded_db):
    _register(client)
    resp = client.put("/me/favorites/999999")
    assert resp.status_code == 404


def test_delete_favorite_never_saved_is_204(client, seeded_db):
    _register(client)
    product = _iphone_product(seeded_db)
    resp = client.delete(f"/me/favorites/{product.id}")
    assert resp.status_code == 204


def test_delete_favorite_removes_it_from_list(client, seeded_db):
    _register(client)
    product = _iphone_product(seeded_db)
    client.put(f"/me/favorites/{product.id}")
    assert client.get("/me/favorites").json()["total"] == 1

    resp = client.delete(f"/me/favorites/{product.id}")
    assert resp.status_code == 204
    assert client.get("/me/favorites").json()["total"] == 0


def test_list_favorites_summarizes_like_search(client, seeded_db):
    _register(client)
    product = _iphone_product(seeded_db)
    client.put(f"/me/favorites/{product.id}")

    resp = client.get("/me/favorites")
    assert resp.status_code == 200
    body = resp.json()
    assert body["page"] == 1
    assert body["page_size"] == 20
    assert body["total"] == 1

    item = body["items"][0]
    assert item["id"] == product.id
    assert item["canonical_title"] == "Apple iPhone 13 128 GB"
    # 4 publicaciones del cluster iphone sembrado (sin filtros, a diferencia de /search).
    assert item["listing_count"] == 4
    assert 0 <= item["best_score"] <= 100
    assert item["min_final_price"] is not None
    assert "saved_at" in item


def test_favorite_ids_lists_only_saved_product_ids(client, seeded_db):
    _register(client)
    iphone = _iphone_product(seeded_db)
    # El cluster `remera` tambien esta sembrado (ver docstring del modulo) pero no se
    # guarda: `product_ids` tiene que traer SOLO lo que efectivamente se puso en favoritos.
    client.put(f"/me/favorites/{iphone.id}")

    resp = client.get("/me/favorites/ids")
    assert resp.status_code == 200
    assert resp.json()["product_ids"] == [iphone.id]


def test_no_response_body_ever_leaks_password(client, seeded_db):
    """Ningun body de `/me/favorites/*` puede contener la substring "password" ni el
    hash real (defensa en profundidad: estos endpoints ni siquiera devuelven `UserOut`,
    pero si en el futuro alguien agrega el usuario a la respuesta, esto lo agarra)."""
    _register(client)
    product = _iphone_product(seeded_db)
    client.put(f"/me/favorites/{product.id}")

    responses = [
        client.get("/me/favorites"),
        client.get("/me/favorites/ids"),
    ]
    for resp in responses:
        text = resp.text.lower()
        assert "password" not in text
        assert "$argon2" not in text

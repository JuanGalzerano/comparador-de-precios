"""Tests de `/auth` (`app/api/routers/auth.py`): registro, login, logout, `/auth/me`.

`client` (de `tests/conftest.py`) reusa la MISMA instancia de `TestClient` dentro de un
test, asi que las cookies que setea `register`/`login` viajan solas en los requests
siguientes del mismo test, igual que un browser real.
"""

from __future__ import annotations

_EMAIL = "ana@example.com"
_PASSWORD = "supersecret1"


def _register(client, email: str = _EMAIL, password: str = _PASSWORD):
    return client.post(
        "/auth/register",
        json={"email": email, "password": password, "display_name": "Ana"},
    )


def test_register_returns_201_and_sets_httponly_cookie(client, db_session):
    resp = _register(client)
    assert resp.status_code == 201

    body = resp.json()
    assert body["email"] == _EMAIL
    assert body["display_name"] == "Ana"
    assert "id" in body and "created_at" in body

    set_cookie = resp.headers.get("set-cookie", "")
    assert "cotejo_session=" in set_cookie
    assert "httponly" in set_cookie.lower()


def test_register_duplicate_email_is_409(client, db_session):
    first = _register(client)
    assert first.status_code == 201

    # Mismo email, distinta capitalizacion: `email_lowercase` + la normalizacion de
    # `RegisterIn` tienen que tratarlo como el mismo registro ya existente.
    second = _register(client, email=_EMAIL.upper())
    assert second.status_code == 409


def test_login_ok(client, db_session):
    _register(client)
    resp = client.post("/auth/login", json={"email": _EMAIL, "password": _PASSWORD})
    assert resp.status_code == 200
    assert resp.json()["email"] == _EMAIL
    assert "cotejo_session=" in resp.headers.get("set-cookie", "")


def test_login_wrong_password_is_401(client, db_session):
    _register(client)
    resp = client.post("/auth/login", json={"email": _EMAIL, "password": "wrong-password"})
    assert resp.status_code == 401
    wrong_detail = resp.json()["detail"]

    # Mismo detail que "email inexistente" (ver siguiente test): no hay forma de
    # distinguir las dos causas desde la respuesta.
    unknown_resp = client.post(
        "/auth/login", json={"email": "nadie@example.com", "password": "cualquier-cosa"}
    )
    assert unknown_resp.status_code == 401
    assert unknown_resp.json()["detail"] == wrong_detail


def test_login_unknown_email_is_401(client, db_session):
    resp = client.post(
        "/auth/login", json={"email": "nadie@example.com", "password": "cualquier-cosa"}
    )
    assert resp.status_code == 401


def test_me_without_cookie_is_401(client, db_session):
    resp = client.get("/auth/me")
    assert resp.status_code == 401


def test_me_with_valid_cookie_returns_user(client, db_session):
    _register(client)
    resp = client.get("/auth/me")
    assert resp.status_code == 200
    assert resp.json()["email"] == _EMAIL


def test_logout_then_me_is_401(client, db_session):
    _register(client)
    assert client.get("/auth/me").status_code == 200

    logout_resp = client.post("/auth/logout")
    assert logout_resp.status_code == 204

    assert client.get("/auth/me").status_code == 401


def test_logout_without_session_is_still_204(client, db_session):
    # Logout de "no estoy logueado" es un no-op, no un error.
    resp = client.post("/auth/logout")
    assert resp.status_code == 204


def test_no_response_body_ever_leaks_password(client, db_session):
    """Ningun body de `/auth/*` puede contener la substring "password" ni el hash real
    (`app.security` genera hashes Argon2, que arrancan con `$argon2`)."""
    responses = [
        _register(client),
        client.post("/auth/login", json={"email": _EMAIL, "password": _PASSWORD}),
        client.get("/auth/me"),
    ]
    for resp in responses:
        if resp.status_code == 204 or not resp.content:
            continue
        text = resp.text.lower()
        assert "password" not in text
        assert "$argon2" not in text

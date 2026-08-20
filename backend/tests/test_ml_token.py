"""Tests del proveedor de token de MercadoLibre (`app/services/ml_token.py`).

Sin red: `respx` intercepta el POST a `/oauth/token`. Lo que se prueba es el contrato —
cuando pide token nuevo, cuando reusa el cacheado, y que ninguna falla se propague.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from app.config import settings
from app.services import ml_token


@pytest.fixture(autouse=True)
def _reset_state():
    """El cache vive en memoria del modulo: se limpia entre tests."""
    ml_token._cached_token = None
    ml_token._expires_at = 0.0
    ml_token._next_attempt_at = 0.0
    yield
    ml_token._cached_token = None
    ml_token._expires_at = 0.0
    ml_token._next_attempt_at = 0.0


@pytest.fixture
def _credentials(monkeypatch):
    monkeypatch.setattr(settings, "ml_access_token", None)
    monkeypatch.setattr(settings, "ml_client_id", "123")
    monkeypatch.setattr(settings, "ml_client_secret", "secreto")


def _token_response(token: str = "APP_USR-nuevo", expires_in: int = 21600) -> httpx.Response:
    return httpx.Response(
        200,
        json={"access_token": token, "token_type": "Bearer", "expires_in": expires_in},
    )


def test_sin_credenciales_devuelve_none(monkeypatch):
    monkeypatch.setattr(settings, "ml_access_token", None)
    monkeypatch.setattr(settings, "ml_client_id", None)
    monkeypatch.setattr(settings, "ml_client_secret", None)

    assert ml_token.get_token() is None


def test_token_manual_tiene_precedencia(monkeypatch):
    """ML_ACCESS_TOKEN en el entorno gana: sirve para debuggear sin tocar credenciales."""
    monkeypatch.setattr(settings, "ml_access_token", "APP_USR-a-mano")
    monkeypatch.setattr(settings, "ml_client_id", "123")
    monkeypatch.setattr(settings, "ml_client_secret", "secreto")

    with respx.mock:
        route = respx.post(ml_token.TOKEN_URL).mock(return_value=_token_response())
        assert ml_token.get_token() == "APP_USR-a-mano"
        assert not route.called


@respx.mock
def test_pide_token_con_client_credentials(_credentials):
    route = respx.post(ml_token.TOKEN_URL).mock(return_value=_token_response())

    assert ml_token.get_token() == "APP_USR-nuevo"

    assert route.called
    sent = dict(httpx.QueryParams(route.calls[0].request.content.decode()))
    assert sent["grant_type"] == "client_credentials"
    assert sent["client_id"] == "123"
    assert sent["client_secret"] == "secreto"


@respx.mock
def test_reusa_el_token_cacheado(_credentials):
    """Segunda llamada no vuelve a pegarle a ML: si no, cada request pediria token."""
    route = respx.post(ml_token.TOKEN_URL).mock(return_value=_token_response())

    assert ml_token.get_token() == "APP_USR-nuevo"
    assert ml_token.get_token() == "APP_USR-nuevo"

    assert route.call_count == 1


@respx.mock
def test_renueva_cuando_vencio(_credentials):
    """Se resta un margen al `expires_in`, asi que uno corto ya nace vencido."""
    route = respx.post(ml_token.TOKEN_URL).mock(
        side_effect=[_token_response("viejo", expires_in=10), _token_response("fresco")]
    )

    assert ml_token.get_token() == "viejo"
    assert ml_token.get_token() == "fresco"
    assert route.call_count == 2


@respx.mock
def test_invalidate_fuerza_renovacion(_credentials):
    route = respx.post(ml_token.TOKEN_URL).mock(
        side_effect=[_token_response("primero"), _token_response("segundo")]
    )

    assert ml_token.get_token() == "primero"
    ml_token.invalidate()
    assert ml_token.get_token() == "segundo"
    assert route.call_count == 2


@respx.mock
def test_credenciales_invalidas_no_revientan(_credentials):
    """ML devuelve 400 `invalid_client`. Degrada a None, no propaga."""
    respx.post(ml_token.TOKEN_URL).mock(
        return_value=httpx.Response(400, json={"error": "invalid_client"})
    )

    assert ml_token.get_token() is None


@respx.mock
def test_no_reintenta_en_rafaga_tras_una_falla(_credentials):
    """Credenciales malas no mejoran en 200 ms: no tiene sentido pegarle a ML por request."""
    route = respx.post(ml_token.TOKEN_URL).mock(
        return_value=httpx.Response(400, json={"error": "invalid_client"})
    )

    assert ml_token.get_token() is None
    assert ml_token.get_token() is None

    assert route.call_count == 1


@respx.mock
def test_respuesta_sin_access_token_degrada(_credentials):
    """Un WAF puede responder 200 con HTML o un JSON sin el campo."""
    respx.post(ml_token.TOKEN_URL).mock(return_value=httpx.Response(200, json={"ok": True}))

    assert ml_token.get_token() is None


@respx.mock
def test_error_de_red_degrada(_credentials):
    respx.post(ml_token.TOKEN_URL).mock(side_effect=httpx.ConnectError("sin red"))

    assert ml_token.get_token() is None

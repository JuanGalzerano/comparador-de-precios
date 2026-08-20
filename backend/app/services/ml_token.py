"""Token de MercadoLibre con renovacion automatica.

ML pasa todo por OAuth 2.0 y el token del flujo Client Credentials **dura 6 horas**
sin refresh token. Renovarlo a mano es viable en local y no lo es en produccion: a las
6 horas la ingesta empieza a devolver 403 y la fuente se cae sola.

Este modulo resuelve eso. Guarda el token en memoria del proceso junto con su
vencimiento y pide uno nuevo cuando hace falta, usando `ML_CLIENT_ID` /
`ML_CLIENT_SECRET`.

Precedencia deliberada: si hay `ML_ACCESS_TOKEN` en el entorno, gana. Sirve para
pegar un token a mano y debuggear sin tocar credenciales.

Sin credenciales ni token, devuelve `None` y quien llama degrada igual que hoy (ML
responde 403 y esa fuente queda vacia) — nunca levanta excepcion, porque una falla de
auth de una tienda no puede tumbar una busqueda que las otras cinco pueden contestar.

Thread-safety: los adapters corren en un `ThreadPoolExecutor`, asi que el estado esta
protegido con un `Lock`. Sin el, N hilos que ven el token vencido piden N tokens.
"""

from __future__ import annotations

import logging
import threading
import time

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

TOKEN_URL = "https://api.mercadolibre.com/oauth/token"

#: Margen antes del vencimiento real. Un token que vence en 30 segundos no sirve para
#: una ingesta que tarda minutos, y el reloj del server puede no estar sincronizado.
_EXPIRY_MARGIN_SECONDS = 300

#: Si ML rechaza las credenciales no tiene sentido reintentar en cada request: son
#: malas hasta que alguien cambie el `.env`. Se espera esto entre intentos.
_RETRY_AFTER_FAILURE_SECONDS = 60

_TIMEOUT = 10.0

_lock = threading.Lock()
_cached_token: str | None = None
_expires_at: float = 0.0
_next_attempt_at: float = 0.0


def get_token() -> str | None:
    """Token valido para el header `Authorization`, o `None` si no hay forma de obtenerlo."""
    if manual := settings.ml_access_token:
        return manual

    if not (settings.ml_client_id and settings.ml_client_secret):
        return None

    now = time.monotonic()

    # Camino feliz sin lock: el token cacheado sigue vivo.
    if _cached_token and now < _expires_at:
        return _cached_token

    with _lock:
        # Otro hilo puede haberlo renovado mientras esperabamos el lock.
        now = time.monotonic()
        if _cached_token and now < _expires_at:
            return _cached_token
        if now < _next_attempt_at:
            return None
        return _refresh_locked()


def invalidate() -> None:
    """Descarta el token cacheado. Para llamar cuando ML devuelve 401/403."""
    global _cached_token, _expires_at
    with _lock:
        _cached_token = None
        _expires_at = 0.0


def _refresh_locked() -> str | None:
    """Pide un token nuevo. Se llama SIEMPRE con `_lock` tomado."""
    global _cached_token, _expires_at, _next_attempt_at

    try:
        with httpx.Client(timeout=_TIMEOUT) as client:
            resp = client.post(
                TOKEN_URL,
                headers={"content-type": "application/x-www-form-urlencoded"},
                data={
                    "grant_type": "client_credentials",
                    "client_id": settings.ml_client_id,
                    "client_secret": settings.ml_client_secret,
                },
            )
            resp.raise_for_status()
            payload = resp.json()
    except Exception as exc:  # httpx, JSON invalido, HTML de un WAF: todo degrada igual
        _next_attempt_at = time.monotonic() + _RETRY_AFTER_FAILURE_SECONDS
        # El secret nunca entra al log: `exc` de httpx trae la URL, no el body enviado.
        logger.warning("No se pudo renovar el token de MercadoLibre: %s", exc)
        return None

    token = payload.get("access_token")
    if not token:
        _next_attempt_at = time.monotonic() + _RETRY_AFTER_FAILURE_SECONDS
        logger.warning("La respuesta de token de MercadoLibre no traia `access_token`")
        return None

    # `expires_in` es opcional en la practica: si falta, se asume la ventana documentada.
    try:
        lifetime = int(payload.get("expires_in") or 21600)
    except (TypeError, ValueError):
        lifetime = 21600

    _cached_token = token
    _expires_at = time.monotonic() + max(lifetime - _EXPIRY_MARGIN_SECONDS, 0)
    _next_attempt_at = 0.0
    logger.info("Token de MercadoLibre renovado (vence en %s s)", lifetime)
    return token

"""Hashing de password y tokens de sesion opaca.

Sin dependencias de SQLAlchemy/FastAPI a proposito: es logica pura, testeable sin base ni
app, y reusable desde un script de backfill o una consola si hiciera falta.

Regla dura del modulo: `password_hash` no sale NUNCA de aca en texto plano (obviamente) y
tampoco el hash viaja a ningun schema Pydantic de respuesta, log o `__repr__` en el resto
de la app — esos lugares solo conocen el `id`/`email`/`display_name` del usuario.
"""

from __future__ import annotations

import hashlib
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

_hasher = PasswordHasher()

#: Hash "senuelo" contra el que se verifica cuando el email no existe. Sin esto,
#: `verify_password` retornaria mas rapido para "email inexistente" que para "password
#: incorrecta" (no hay Argon2 de por medio), y esa diferencia de tiempo es exactamente lo
#: que un atacante usa para enumerar emails registrados.
_DUMMY_HASH = _hasher.hash("cotejo-dummy-password")


def hash_password(plain: str) -> str:
    """Hashea una password en texto plano con Argon2id."""
    return _hasher.hash(plain)


def verify_password(plain: str, hashed: str | None) -> bool:
    """Verifica `plain` contra `hashed`.

    `hashed=None` (usuario no encontrado) igual ejecuta un hash Argon2 completo contra
    `_DUMMY_HASH`, y siempre devuelve `False`: el costo en tiempo de "no existe" queda
    igualado al de "existe pero la password no matchea".
    """
    try:
        _hasher.verify(hashed if hashed is not None else _DUMMY_HASH, plain)
        return hashed is not None
    except VerifyMismatchError:
        return False


def needs_rehash(hashed: str) -> bool:
    """Si el hash quedo con parametros viejos (costo subido desde que se creo)."""
    return _hasher.check_needs_rehash(hashed)


def new_session_token() -> str:
    """Token opaco de sesion: lo que recibe el navegador en la cookie."""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """sha256 hex del token: lo que se persiste en `user_session.token_hash`."""
    return hashlib.sha256(token.encode()).hexdigest()

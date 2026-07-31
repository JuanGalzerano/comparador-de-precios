"""Dependencias compartidas de los endpoints."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated

from fastapi import Depends, HTTPException
from fastapi.security import APIKeyCookie
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models.user_account import UserAccount
from app.models.user_session import UserSession
from app.security import hash_token

#: Alias para no repetir `db: Session = Depends(get_db)` en cada endpoint.
#:
#:     @router.get("/algo")
#:     def algo(db: DbSession) -> ...:
DbSession = Annotated[Session, Depends(get_db)]

#: `auto_error=False`: la ausencia de cookie NO es un 401 automatico de FastAPI, la
#: maneja `get_optional_user` (que devuelve `None`, no todos los endpoints requieren
#: usuario logueado).
_cookie_scheme = APIKeyCookie(name=settings.session_cookie_name, auto_error=False)


def get_optional_user(
    db: DbSession, token: str | None = Depends(_cookie_scheme)
) -> UserAccount | None:
    """Resuelve el usuario de la cookie de sesion, o `None` si no hay sesion valida.

    Una sesion vencida se borra en el momento (housekeeping perezoso: no hace falta un
    cron aparte para limpiar `user_session`, cada request que la pisa la elimina).
    """
    if not token:
        return None
    session = db.scalar(select(UserSession).where(UserSession.token_hash == hash_token(token)))
    if session is None:
        return None

    expires_at = session.expires_at
    if expires_at.tzinfo is None:
        # Solo pasa en SQLite (los tests): el identity map de la Session usa referencias
        # debiles, asi que un `UserSession` creado en un request anterior puede ya haber
        # sido recolectado por el GC al llegar aca, y la siguiente query lo recarga
        # DE VERDAD desde la fila. El tipo `DATETIME` de SQLite no persiste el offset de
        # timezone (a diferencia de `timestamptz` en Postgres), asi que ese reload vuelve
        # naive. Todo en este schema se guarda en UTC (ver `app/models/base.py`), asi que
        # asumir UTC en ausencia de tzinfo es seguro y no cambia el comportamiento real
        # contra Postgres (que siempre devuelve aware).
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at <= datetime.now(timezone.utc):
        db.delete(session)
        db.commit()
        return None
    user = db.get(UserAccount, session.user_id)
    if user is None or not user.is_active:
        return None
    return user


def get_current_user(user: UserAccount | None = Depends(get_optional_user)) -> UserAccount:
    """Igual que `get_optional_user` pero exige sesion valida: 401 si no hay."""
    if user is None:
        raise HTTPException(status_code=401, detail="no autenticado")
    return user


#: Para endpoints que REQUIEREN estar logueado (`/me/favorites/*`).
CurrentUser = Annotated[UserAccount, Depends(get_current_user)]
#: Para endpoints que se comportan distinto si hay usuario pero no lo exigen.
OptionalUser = Annotated[UserAccount | None, Depends(get_optional_user)]

__all__ = [
    "CurrentUser",
    "DbSession",
    "OptionalUser",
    "get_current_user",
    "get_db",
    "get_optional_user",
]

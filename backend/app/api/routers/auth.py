"""`/auth` — registro, login, logout y "quien soy" de cuentas de usuario.

Publico, sin gate (a diferencia de `/me/favorites`, que exige sesion): son justamente
los endpoints que dejan de estar anonimo. La sesion es un token opaco (ver
`app/security.py`), no un JWT: el navegador recibe el token en una cookie `HttpOnly`;
el servidor solo guarda su hash SHA-256 (`user_session.token_hash`).

`POST /auth/login` responde el MISMO 401 con el MISMO `detail` sea cual sea la causa
(email inexistente, password incorrecta, cuenta desactivada): decirle a un atacante
"ese email no existe" en vez de "password incorrecta" es enumerar cuentas registradas.
Igualar la respuesta no alcanza si el TIEMPO de respuesta delata la diferencia, por eso
`verify_password(password, hashed=None)` corre el hash Argon2 completo aunque no haya
usuario (ver docstring de `app.security.verify_password`).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.deps import CurrentUser, DbSession
from app.config import settings
from app.models.user_account import UserAccount
from app.models.user_session import UserSession
from app.schemas.auth import LoginIn, RegisterIn, UserOut
from app.security import hash_password, hash_token, new_session_token, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])

#: Mismo mensaje para email-inexistente, password-incorrecta y cuenta-desactivada (ver
#: docstring del modulo).
_INVALID_CREDENTIALS_DETAIL = "email o password incorrectos"


def _set_session_cookie(response: Response, token: str) -> None:
    """Cookie de sesion. Sin `domain=`: el scope por defecto (host exacto del request)
    alcanza para un frontend en otro origen consumido via CORS + credentials, y evita
    el footgun de una cookie que se filtra a subdominios no pensados para esto."""
    response.set_cookie(
        key=settings.session_cookie_name,
        value=token,
        max_age=settings.session_ttl_days * 86400,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.session_cookie_samesite,
        path="/",
    )


def _create_session(db: DbSession, user: UserAccount) -> str:
    """Crea la fila de `user_session` y devuelve el token opaco (no persistido tal cual,
    ver `UserSession.token_hash`)."""
    token = new_session_token()
    expires_at = datetime.now(timezone.utc) + timedelta(days=settings.session_ttl_days)
    db.add(UserSession(user_id=user.id, token_hash=hash_token(token), expires_at=expires_at))
    db.commit()
    return token


@router.post("/register", response_model=UserOut, status_code=201)
def register(payload: RegisterIn, db: DbSession, response: Response) -> UserOut:
    user = UserAccount(
        email=payload.email,
        password_hash=hash_password(payload.password),
        display_name=payload.display_name,
    )
    db.add(user)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="el email ya esta registrado") from None
    db.commit()
    db.refresh(user)

    token = _create_session(db, user)
    _set_session_cookie(response, token)
    return UserOut.model_validate(user)


@router.post("/login", response_model=UserOut)
def login(payload: LoginIn, db: DbSession, response: Response) -> UserOut:
    user = db.scalar(select(UserAccount).where(UserAccount.email == payload.email))

    # `hashed=None` cuando no hay usuario: iguala el tiempo de respuesta contra el caso
    # "password incorrecta" (ver docstring del modulo).
    password_ok = verify_password(payload.password, user.password_hash if user else None)
    if user is None or not password_ok or not user.is_active:
        raise HTTPException(status_code=401, detail=_INVALID_CREDENTIALS_DETAIL)

    token = _create_session(db, user)
    _set_session_cookie(response, token)
    return UserOut.model_validate(user)


@router.post("/logout", status_code=204)
def logout(request: Request, db: DbSession, response: Response) -> None:
    """204 siempre, tenga o no una sesion valida: logout de "no estoy logueado" no es
    un error, es un no-op. Se lee la cookie cruda (no `OptionalUser`) porque hace falta
    el `token_hash` exacto para borrar la fila; no alcanza con saber quien es el usuario."""
    token = request.cookies.get(settings.session_cookie_name)
    if token:
        db.execute(
            UserSession.__table__.delete().where(UserSession.token_hash == hash_token(token))
        )
        db.commit()

    # Mismos `path`/`samesite`/`secure` que al setearla: un browser no borra una cookie
    # si estos atributos no matchean exactamente los originales.
    response.delete_cookie(
        key=settings.session_cookie_name,
        path="/",
        samesite=settings.session_cookie_samesite,
        secure=settings.cookie_secure,
    )


@router.get("/me", response_model=UserOut)
def me(user: CurrentUser) -> UserOut:
    """401 (via `CurrentUser`/`get_current_user`) si no hay sesion valida."""
    return UserOut.model_validate(user)

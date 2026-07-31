"""Schemas de `/auth` (registro, login, `/auth/me`).

`UserOut` es el UNICO schema que expone datos de `UserAccount`: nunca incluye
`password_hash` (ni ningun otro schema de la app lo hace, ver `app/security.py`).
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    display_name: str | None
    created_at: datetime


class RegisterIn(BaseModel):
    email: EmailStr
    #: Sin tope superior "razonable" arbitrario mas alla de 128: Argon2 hashea con costo
    #: fijo independiente del largo del input, no hay ventaja de DoS en aceptar mas.
    password: str = Field(min_length=8, max_length=128)
    display_name: str | None = Field(default=None, max_length=80)

    @field_validator("email", mode="after")
    @classmethod
    def _normalize_email(cls, value: str) -> str:
        # `EmailStr` valida formato pero no normaliza case: dos registros con
        # "User@x.com" / "user@x.com" tienen que ser la MISMA cuenta (ver
        # `email_lowercase` en `app.models.user_account`).
        return value.lower().strip()


class LoginIn(BaseModel):
    email: EmailStr
    #: `min_length=1`, no 8: una password vieja mas corta que la politica actual tiene
    #: que poder seguir logueando (la politica de largo minimo es solo para altas nuevas).
    password: str = Field(min_length=1, max_length=128)

    @field_validator("email", mode="after")
    @classmethod
    def _normalize_email(cls, value: str) -> str:
        return value.lower().strip()

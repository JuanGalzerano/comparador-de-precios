"""`user_account` — cuenta de usuario registrada (email + password).

Separada de `user_event` (que es anonimo, `anon_id` de cookie/localStorage sin cuenta
detras): esta tabla es la identidad real que habilita login, favoritos persistentes y,
mas adelante, sincronizar el historial anonimo con una cuenta. `email_lowercase` fuerza
en la base lo que `RegisterIn`/`LoginIn` ya normalizan en la capa de schema (defensa en
profundidad: cualquier insert que no pase por esos schemas — un script, una migracion de
datos — tampoco puede crear un duplicado por mayusculas).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Boolean, CheckConstraint, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, IdMixin, TimestampMixin

if TYPE_CHECKING:
    from app.models.saved_product import SavedProduct
    from app.models.user_session import UserSession


class UserAccount(IdMixin, TimestampMixin, Base):
    __tablename__ = "user_account"

    #: Normalizado a lowercase por `RegisterIn`/`LoginIn` (`field_validator`) antes de
    #: llegar aca; `email_lowercase` es el cinturon-y-tiradores a nivel base.
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)

    #: SIEMPRE un hash Argon2id (`app.security.hash_password`). NUNCA texto plano y
    #: NUNCA expuesto en un schema de respuesta, log o `__repr__` (ver `app/security.py`).
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)

    display_name: Mapped[str | None] = mapped_column(String(80))

    #: Gate de login/sesion: una cuenta desactivada (baja logica, moderacion) no puede
    #: loguearse ni mantener sesiones validas (`get_optional_user` la trata como ausente).
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )

    sessions: Mapped[list["UserSession"]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )
    saved_products: Mapped[list["SavedProduct"]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )

    __table_args__ = (CheckConstraint("email = lower(email)", name="email_lowercase"),)

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<UserAccount {self.id} {self.email!r}>"

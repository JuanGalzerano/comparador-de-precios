"""`user_session` — sesion de login activa (token opaco, no JWT).

El cookie que recibe el navegador es un token aleatorio (`app.security.new_session_token`);
lo unico que se persiste aca es su hash SHA-256 (`token_hash`), nunca el token en si, para
que un dump de esta tabla no habilite secuestrar sesiones. Sin `TimestampMixin` a proposito:
una fila de sesion nunca se actualiza despues de creada, solo se crea y se borra. La
revocacion (logout, expiracion detectada en `get_optional_user`) es un DELETE de la fila,
no una columna `revoked_at`: menos estado que mantener consistente y una sesion revocada
deja de existir en vez de quedar "marcada" para siempre en la tabla.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, BigId, IdMixin, TZDateTime

if TYPE_CHECKING:
    from app.models.user_account import UserAccount


class UserSession(IdMixin, Base):
    __tablename__ = "user_session"

    user_id: Mapped[int] = mapped_column(
        BigId, ForeignKey("user_account.id", ondelete="CASCADE"), nullable=False
    )

    #: sha256 hex (64 chars) del token opaco que ve el cliente en la cookie. `unique`
    #: porque es efectivamente la clave de lookup de `get_optional_user`.
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)

    expires_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False)

    #: Sin `onupdate`: a diferencia de `TimestampMixin.created_at`, esta fila no tiene
    #: `updated_at` porque nunca se actualiza (ver docstring del modulo).
    created_at: Mapped[datetime] = mapped_column(
        TZDateTime, nullable=False, server_default=func.now()
    )

    user: Mapped["UserAccount"] = relationship(back_populates="sessions")

    __table_args__ = (
        # Barrido periodico de sesiones vencidas (housekeeping, todavia no implementado).
        Index("ix_user_session_expires_at", "expires_at"),
        # `get_optional_user` no la necesita (busca por `token_hash`, que ya es unique),
        # pero listar/borrar todas las sesiones de un usuario (logout-all-devices,
        # futuro) sin un full scan si la va a necesitar.
        Index("ix_user_session_user_id", "user_id"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<UserSession {self.id} user_id={self.user_id}>"

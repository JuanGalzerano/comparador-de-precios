"""`saved_product` — favoritos: que `product` guardo cada `user_account`.

Tabla de union simple (usuario, producto) con un timestamp de cuando se guardo. Sin
`TimestampMixin`: no hay nada que actualizar despues de creada (guardar de nuevo un
producto ya guardado es un no-op idempotente en el endpoint, no una fila que se
"reactiva"). La relacion con `Product` es UNIDIRECCIONAL a proposito: `Product` no gana
un `relationship` inverso (`saved_by`) porque el modelo de producto no necesita saber
quien lo guardo para nada de lo que hace hoy (busqueda, ficha, scoring), y agregarlo
seria una relationship que ningun endpoint usa.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, BigId, IdMixin, TZDateTime

if TYPE_CHECKING:
    from app.models.product import Product
    from app.models.user_account import UserAccount


class SavedProduct(IdMixin, Base):
    __tablename__ = "saved_product"

    user_id: Mapped[int] = mapped_column(
        BigId, ForeignKey("user_account.id", ondelete="CASCADE"), nullable=False
    )
    product_id: Mapped[int] = mapped_column(
        BigId, ForeignKey("product.id", ondelete="CASCADE"), nullable=False
    )

    created_at: Mapped[datetime] = mapped_column(
        TZDateTime, nullable=False, server_default=func.now()
    )

    user: Mapped["UserAccount"] = relationship(back_populates="saved_products")
    #: Unidireccional: ver docstring del modulo.
    product: Mapped["Product"] = relationship()

    __table_args__ = (
        # Un usuario no puede guardar el mismo producto dos veces: el endpoint
        # `PUT /me/favorites/{id}` se apoya en esto para ser idempotente (upsert via
        # `IntegrityError` + rollback en vez de un SELECT-then-INSERT con carrera).
        UniqueConstraint("user_id", "product_id", name="uq_saved_product_user_product"),
        # Query caliente: "favoritos del usuario X, mas recientes primero" (`GET
        # /me/favorites`, paginado).
        Index("ix_saved_product_user_id_created_at", "user_id", "created_at"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<SavedProduct user_id={self.user_id} product_id={self.product_id}>"

"""`price_history` — snapshot de precio por publicacion en el tiempo.

Alimenta el grafico de historial en la ficha de producto y `/ofertas` (precio actual vs.
mediana de 90 dias). Se escribe una fila por corrida de ingesta SOLO cuando el precio o el
costo de envio cambian respecto del ultimo snapshot (evita crecer linealmente con la
frecuencia del cron); esa logica vive en el worker de ingesta, no en el schema.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, ForeignKey, Index, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, BigId, IdMixin, Money, TZDateTime

if TYPE_CHECKING:
    from app.models.listing import Listing


class PriceHistory(IdMixin, Base):
    __tablename__ = "price_history"

    listing_id: Mapped[int] = mapped_column(
        BigId, ForeignKey("listing.id", ondelete="CASCADE"), nullable=False
    )
    price: Mapped[Decimal] = mapped_column(Money, nullable=False)
    shipping_cost: Mapped[Decimal | None] = mapped_column(Money)
    captured_at: Mapped[datetime] = mapped_column(
        TZDateTime, nullable=False, server_default=func.now()
    )

    listing: Mapped["Listing"] = relationship(back_populates="price_points")

    __table_args__ = (
        # Unico acceso real: la serie de una publicacion en orden cronologico
        # (y "el ultimo snapshot" = primer resultado en DESC).
        Index("ix_price_history_listing_id_captured_at", "listing_id", "captured_at"),
        CheckConstraint("price >= 0", name="price_non_negative"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<PriceHistory listing={self.listing_id} at={self.captured_at}>"

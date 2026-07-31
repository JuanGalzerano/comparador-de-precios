"""`product_match` — evidencia de por que una publicacion se vinculo a un producto.

`listing.product_id` es el resultado aplicado; esta tabla es el registro auditable de como
se llego a el, y la cola de revision del panel admin. Una publicacion puede tener varios
candidatos (fuzzy/embedding devuelven N con distinta `confidence`), por eso la unicidad es
por par (listing, product) y no por listing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Float,
    ForeignKey,
    Index,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.enums import MatchMethod
from app.models.base import Base, BigId, IdMixin, TimestampMixin, pg_enum

if TYPE_CHECKING:
    from app.models.listing import Listing
    from app.models.product import Product


class ProductMatch(IdMixin, TimestampMixin, Base):
    __tablename__ = "product_match"

    listing_id: Mapped[int] = mapped_column(
        BigId, ForeignKey("listing.id", ondelete="CASCADE"), nullable=False
    )
    product_id: Mapped[int] = mapped_column(
        BigId, ForeignKey("product.id", ondelete="CASCADE"), nullable=False
    )
    method: Mapped[MatchMethod] = mapped_column(
        pg_enum(MatchMethod, "match_method"), nullable=False
    )
    #: 0.0 - 1.0. Por convencion `catalog_id` y `manual` escriben 1.0.
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    reviewed_by_human: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )

    listing: Mapped["Listing"] = relationship(back_populates="matches")
    product: Mapped["Product"] = relationship(back_populates="matches")

    __table_args__ = (
        UniqueConstraint("listing_id", "product_id", name="uq_product_match_listing_product"),
        # Cola de revision del panel admin: lo no revisado, peor confianza primero.
        Index("ix_product_match_reviewed_by_human_confidence", "reviewed_by_human", "confidence"),
        Index("ix_product_match_product_id", "product_id"),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence_range"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return (
            f"<ProductMatch listing={self.listing_id} product={self.product_id} "
            f"method={self.method} conf={self.confidence}>"
        )

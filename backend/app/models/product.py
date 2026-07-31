"""`product` — el producto canonico contra el que se agrupan las publicaciones.

La UI muestra clusters de publicaciones del mismo producto, no publicaciones sueltas:
esta tabla es el cluster. `catalog_product_id` es el `product_key` deterministico cuando
la fuente lo provee (ML expone `catalog_product_id`); si no existe, el producto se crea
por matching propio (marca + modelo + atributos) y `catalog_product_id` queda NULL.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, IdMixin, JsonDict, JSONBType, TimestampMixin

if TYPE_CHECKING:
    from app.models.listing import Listing
    from app.models.product_match import ProductMatch


class Product(IdMixin, TimestampMixin, Base):
    __tablename__ = "product"

    canonical_title: Mapped[str] = mapped_column(String(512), nullable=False)
    brand: Mapped[str | None] = mapped_column(String(128))
    model: Mapped[str | None] = mapped_column(String(128))
    category: Mapped[str | None] = mapped_column(String(128))

    #: Id de catalogo de la fuente que lo origino (p.ej. `MLA22811322`).
    #: UNIQUE parcial: Postgres permite multiples NULL, asi que los productos creados por
    #: matching propio no chocan entre si, pero un mismo catalog id no se duplica nunca.
    catalog_product_id: Mapped[str | None] = mapped_column(String(64), unique=True)

    #: Atributos normalizados para el matching cross-retailer (capacidad, color, EAN/GTIN,
    #: anio, etc.). Sin schema fijo porque varia por categoria.
    attributes_json: Mapped[JsonDict] = mapped_column(
        JSONBType, nullable=False, default=dict, server_default="{}"
    )

    listings: Mapped[list["Listing"]] = relationship(back_populates="product")
    matches: Mapped[list["ProductMatch"]] = relationship(
        back_populates="product",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __table_args__ = (
        Index("ix_product_brand_model", "brand", "model"),
        Index("ix_product_category", "category"),
        # TODO(matching v2): indice GIN trigram sobre `canonical_title` para el matching
        # fuzzy (`CREATE EXTENSION pg_trgm` + `gin_trgm_ops`). No se incluye en la
        # migracion inicial porque crear la extension requiere privilegios de superusuario
        # y todavia no hay una segunda fuente contra la cual matchear.
    )

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<Product {self.id} {self.canonical_title!r}>"

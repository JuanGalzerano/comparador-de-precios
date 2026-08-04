"""`product` — el producto canonico contra el que se agrupan las publicaciones.

La UI muestra clusters de publicaciones del mismo producto, no publicaciones sueltas:
esta tabla es el cluster. `catalog_product_id` es el `product_key` deterministico cuando
la fuente lo provee (ML expone `catalog_product_id`); si no existe, el producto se crea
por matching propio (marca + modelo + atributos) y `catalog_product_id` queda NULL.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import (
    Base,
    IdMixin,
    JsonDict,
    JSONBType,
    TimestampMixin,
    TZDateTime,
)

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

    # --- Uso: alimenta la politica de evicción del cache ---------------------
    # La base es un cache de lo que la gente busca (ver `app/services/live_search.py`),
    # asi que necesita saber que se usa y que no. Estas dos columnas son las entradas de
    # `app/services/maintenance.py`: se borra lo viejo Y poco visto, nunca solo por edad.
    #: Ultima vez que este producto aparecio en resultados o se abrio su ficha.
    last_accessed_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    #: Cuantas veces paso eso. Un producto muy buscado sobrevive aunque tenga unos dias.
    access_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
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
        # La evicción busca "lo menos usado y mas viejo": este indice es el que hace que
        # esa consulta no recorra toda la tabla.
        Index("ix_product_access_count_last_accessed", "access_count", "last_accessed_at"),
        # TODO(matching v2): indice GIN trigram sobre `canonical_title` para el matching
        # fuzzy (`CREATE EXTENSION pg_trgm` + `gin_trgm_ops`). No se incluye en la
        # migracion inicial porque crear la extension requiere privilegios de superusuario
        # y todavia no hay una segunda fuente contra la cual matchear.
    )

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<Product {self.id} {self.canonical_title!r}>"

"""`listing` — una publicacion concreta en una fuente concreta.

Es la unidad que se ingesta y la que se muestra en la tabla comparativa. `product_id` es
NULLABLE a proposito: el matching corre en un paso posterior y no debe bloquear la ingesta
(una publicacion sin producto asignado es un estado valido y esperado).

Los nombres de campo siguen el modelo del plan; entre parentesis, el campo equivalente del
prototipo (`project/Cotejo - Comparador.dc.html`) que consume `scoreOf()`.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Computed,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.enums import ItemCondition, WarrantyType
from app.models.base import (
    Base,
    BigId,
    IdMixin,
    Money,
    TimestampMixin,
    TZDateTime,
    pg_enum,
)

if TYPE_CHECKING:
    from app.models.price_history import PriceHistory
    from app.models.product import Product
    from app.models.product_match import ProductMatch
    from app.models.retailer_source import RetailerSource


class Listing(IdMixin, TimestampMixin, Base):
    __tablename__ = "listing"

    # --- Vinculos ----------------------------------------------------------
    product_id: Mapped[int | None] = mapped_column(
        BigId, ForeignKey("product.id", ondelete="SET NULL")
    )
    retailer_source_id: Mapped[int] = mapped_column(
        BigId, ForeignKey("retailer_source.id", ondelete="CASCADE"), nullable=False
    )

    #: Id de la publicacion en la fuente (`MLA12345678`, sku VTEX, id de producto SEPA).
    #: Junto a `retailer_source_id` forma la clave natural de upsert de la ingesta.
    external_id: Mapped[str] = mapped_column(String(128), nullable=False)

    #: Id del producto en el catalogo de la fuente (`catalog_product_id` de ML). Cuando
    #: existe es la señal de matching mas fuerte que hay: dos publicaciones con el mismo
    #: valor son el mismo producto, sin heuristica de por medio. NULL en las fuentes que
    #: no tienen concepto de catalogo compartido (VTEX).
    catalog_product_id: Mapped[str | None] = mapped_column(String(64))

    # --- Vendedor ----------------------------------------------------------
    seller_name: Mapped[str | None] = mapped_column(String(256))
    #: String y no int: ML usa ids numericos, VTEX/scrapers usan slugs.
    seller_id: Mapped[str | None] = mapped_column(String(64))
    #: `l.level` en scoreOf. Texto libre por diseno (ver `SELLER_LEVELS` en app/enums.py).
    seller_level: Mapped[str | None] = mapped_column(String(32))
    seller_sales: Mapped[int | None] = mapped_column(Integer)
    #: `l.official` en scoreOf. Guarda el NOMBRE de la tienda oficial (`"Fravega"`) o NULL
    #: si no es tienda oficial: NULL/no-NULL da el booleano que usa el score, y ademas
    #: sirve para el label "Tienda oficial · X" sin una tabla extra.
    official_store: Mapped[str | None] = mapped_column(String(128))

    # --- Publicacion -------------------------------------------------------
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    condition: Mapped[ItemCondition] = mapped_column(
        pg_enum(ItemCondition, "item_condition"),
        nullable=False,
        default=ItemCondition.UNKNOWN,
        server_default=ItemCondition.UNKNOWN.value,
    )
    permalink: Mapped[str] = mapped_column(Text, nullable=False)

    # --- Precio ------------------------------------------------------------
    #: Precio de venta publicado, en ARS. El schema es mono-moneda por ahora
    #: (ver `NormalizedListingInput.currency`, que valida antes de escribir aca).
    price: Mapped[Decimal] = mapped_column(Money, nullable=False)
    #: `l.ship`. 0 = envio gratis confirmado; NULL = la fuente no informa costo de envio.
    shipping_cost: Mapped[Decimal | None] = mapped_column(Money)
    #: Columna GENERADA por la base (`price + coalesce(shipping_cost, 0)`).
    #:
    #: DESVIACION del plan, que la listaba como columna comun: `scoreOf()` define
    #: `final = l.price + l.ship` literalmente, y es el campo por el que se ordena toda la
    #: tabla comparativa. Calculada por Postgres no puede desincronizarse con `price` y se
    #: puede indexar. Si en el futuro una fuente informa un precio final que no es la suma
    #: (descuento por transferencia/efectivo, tipico en retail AR), esto pasa a columna
    #: comun con una migracion.
    final_price: Mapped[Decimal] = mapped_column(
        Money,
        Computed("price + coalesce(shipping_cost, 0)", persisted=True),
    )

    # --- Financiacion ------------------------------------------------------
    installments_qty: Mapped[int | None] = mapped_column(SmallInteger)
    installments_amount: Mapped[Decimal | None] = mapped_column(Money)
    #: `l.free` (cuotas sin interes).
    interest_free: Mapped[bool | None] = mapped_column(Boolean)

    # --- Logistica ---------------------------------------------------------
    #: `l.full` en scoreOf (MercadoEnvios Full / envio gestionado por la plataforma).
    #:
    #: DESVIACION: no estaba en la lista de columnas del plan, pero `scoreOf()` le asigna
    #: 0.5 de los 1.0 puntos del eje "perks". Sin esta columna el port de la formula no se
    #: puede hacer fiel. NULL = la fuente no tiene el concepto.
    fulfillment: Mapped[bool | None] = mapped_column(Boolean)

    # --- Reputacion del item -----------------------------------------------
    #: 0.00 - 5.00. NULL = sin dato (distinto de 0, que scoreOf castiga).
    rating: Mapped[Decimal | None] = mapped_column(Numeric(3, 2))
    reviews_count: Mapped[int | None] = mapped_column(Integer)

    # --- Garantia ----------------------------------------------------------
    warranty_months: Mapped[int | None] = mapped_column(SmallInteger)
    warranty_type: Mapped[WarrantyType] = mapped_column(
        pg_enum(WarrantyType, "warranty_type"),
        nullable=False,
        default=WarrantyType.UNKNOWN,
        server_default=WarrantyType.UNKNOWN.value,
    )

    # --- Trazabilidad ------------------------------------------------------
    #: Cuando se leyo de la fuente (no cuando se escribio la fila).
    fetched_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False)

    # --- Relaciones --------------------------------------------------------
    product: Mapped["Product | None"] = relationship(back_populates="listings")
    retailer_source: Mapped["RetailerSource"] = relationship(back_populates="listings")
    price_points: Mapped[list["PriceHistory"]] = relationship(
        back_populates="listing",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="PriceHistory.captured_at",
    )
    matches: Mapped[list["ProductMatch"]] = relationship(
        back_populates="listing",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __table_args__ = (
        # Clave natural: identifica la publicacion entre corridas de ingesta (upsert).
        UniqueConstraint("retailer_source_id", "external_id", name="uq_listing_source_external"),
        # Query caliente: todas las publicaciones de un producto ordenadas por precio final.
        Index("ix_listing_product_id_final_price", "product_id", "final_price"),
        # Salud/frescura por fuente y barridos de re-ingesta ("lo mas viejo primero").
        Index("ix_listing_retailer_source_id_fetched_at", "retailer_source_id", "fetched_at"),
        # Via deterministica del matcher: "todas las publicaciones de este catalog id".
        Index("ix_listing_catalog_product_id", "catalog_product_id"),
        # `/sources`: agregado por (producto, fuente) con min(final_price). El indice de
        # arriba no lo cubre (le falta la fuente) y forzaba un scan de toda la tabla.
        Index(
            "ix_listing_product_retailer_price",
            "product_id",
            "retailer_source_id",
            "final_price",
        ),
        CheckConstraint("price >= 0", name="price_non_negative"),
        CheckConstraint(
            "shipping_cost IS NULL OR shipping_cost >= 0", name="shipping_cost_non_negative"
        ),
        CheckConstraint("rating IS NULL OR (rating >= 0 AND rating <= 5)", name="rating_range"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<Listing {self.id} src={self.retailer_source_id} ext={self.external_id!r}>"

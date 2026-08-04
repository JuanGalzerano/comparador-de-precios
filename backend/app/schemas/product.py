"""Schemas de respuesta de `GET /products/{id}` y `GET /products/{id}/price-history`.

`ListingOut` mapea 1:1 los campos de `listing` que consume la tabla comparativa del
mock (`renderVals()`, `project/Cotejo - Comparador.dc.html:585-670`) mas el `score`
calculado server-side. `permalink` siempre viaja: es el CTA de la UI.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from app.enums import ItemCondition, WarrantyType


class ListingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    #: CTA de la UI: tiene que viajar siempre (ver docstring del router).
    permalink: str
    condition: ItemCondition

    price: Decimal
    shipping_cost: Decimal | None
    final_price: Decimal

    installments_qty: int | None
    installments_amount: Decimal | None
    interest_free: bool | None

    seller_name: str | None
    seller_level: str | None
    seller_sales: int | None
    #: Nombre de la tienda oficial, o `None` si no lo es (`l.official` del mock).
    official_store: str | None

    fulfillment: bool | None

    rating: Decimal | None
    reviews_count: int | None

    warranty_months: int | None
    warranty_type: WarrantyType

    #: De qué tienda salió este precio. Sin esto la tabla comparativa no se puede leer:
    #: el usuario ve cinco precios distintos sin saber a qué sitio pertenece cada uno.
    retailer_slug: str | None = None
    retailer_name: str | None = None

    #: `scoreOf()` calculado server-side contra el set filtrado (0-100).
    score: int


class ProductDetailOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    canonical_title: str
    brand: str | None
    model: str | None
    category: str | None
    catalog_product_id: str | None

    #: Ya ordenadas/filtradas segun los query params del request.
    listings: list[ListingOut]


class PriceHistoryPoint(BaseModel):
    """Un punto crudo de `price_history`. Sin agregacion: ver docstring del router."""

    listing_id: int
    captured_at: datetime
    price: Decimal
    shipping_cost: Decimal | None


class PriceHistoryResponse(BaseModel):
    product_id: int
    since: datetime
    points: list[PriceHistoryPoint]

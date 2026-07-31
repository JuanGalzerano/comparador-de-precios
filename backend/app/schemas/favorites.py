"""Schemas de `/me/favorites`.

`SavedProductOut` es deliberadamente parecido a `ProductClusterOut` (`app/schemas/
search.py`): mismo resumen de cluster (conteo + min/max de `final_price` + mejor score)
para que la UI pueda reusar el mismo componente de tarjeta de producto en resultados de
busqueda y en la pagina de favoritos. La diferencia es `min_final_price`/
`max_final_price` NULLABLE aca: a diferencia de `/search` (que solo devuelve productos
con al menos una publicacion matcheada), un producto guardado puede haberse quedado sin
ninguna publicacion vigente (todas dadas de baja) y el favorito sigue existiendo.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class SavedProductOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    canonical_title: str
    brand: str | None
    model: str | None
    category: str | None
    catalog_product_id: str | None

    listing_count: int
    #: `None`: puede no tener publicaciones vigentes (ver docstring del modulo).
    min_final_price: Decimal | None
    max_final_price: Decimal | None
    best_score: int

    saved_at: datetime


class SavedProductsResponse(BaseModel):
    items: list[SavedProductOut]
    page: int
    page_size: int
    total: int


class SavedProductIdsResponse(BaseModel):
    """Solo los ids: lo que la UI necesita para pintar el corazon de "guardado" en
    listados (`/search`, `/products`) sin pedir el detalle completo de cada favorito."""

    product_ids: list[int]

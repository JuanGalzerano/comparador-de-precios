"""Schemas de respuesta de `GET /search`.

La UI de resultados muestra clusters de publicaciones del mismo producto (ver
`groups` en `project/Cotejo - Comparador.dc.html:672-685`), no publicaciones sueltas.
`ProductClusterOut` es ese resumen; `SearchResponse` es el sobre paginado.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class ProductClusterOut(BaseModel):
    """Resumen de un `product` y el set de `listing` que matcheo la busqueda.

    `listing_count`/`min_final_price`/`max_final_price`/`best_score` se calculan SOLO
    sobre el set filtrado (post `q`/`category`/`condition`), no sobre todas las
    publicaciones del producto: son "lo que el usuario esta viendo", igual que
    `renderVals()` normaliza el score contra el set visible.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    canonical_title: str
    brand: str | None
    model: str | None
    category: str | None
    catalog_product_id: str | None

    listing_count: int
    #: Tiendas distintas que publican este producto. Es el dato que justifica el
    #: producto entero ("lo comparamos en 3 tiendas"), distinto de `listing_count`
    #: (una misma tienda puede tener varias publicaciones del mismo producto).
    retailer_count: int = 1
    #: Nombres de esas tiendas, para mostrarlas en la tarjeta sin un fetch extra.
    retailer_names: list[str] = []
    min_final_price: Decimal
    max_final_price: Decimal
    #: Mejor `score_of()` del set filtrado (0-100).
    best_score: int
    #: URL externa directa (solo para resultados live de ML; None para items de la DB).
    permalink: str | None = None


class SearchResponse(BaseModel):
    """Sobre paginado de `/search`. La paginacion no existe en el mock (gap del plan)."""

    items: list[ProductClusterOut]
    page: int
    page_size: int
    total: int
    #: Consulta que efectivamente devolvio estos resultados, cuando NO es la que pidio
    #: el usuario. Se completa solo si la busqueda exacta dio cero y hubo que soltar
    #: palabras (ver `_relaxations` en el router): el frontend lo muestra como
    #: "no encontramos X, estos son los resultados de Y". `None` = busqueda exacta.
    relaxed_query: str | None = None

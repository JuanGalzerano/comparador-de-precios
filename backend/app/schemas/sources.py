"""Schemas de `GET /sources` — transparencia de fuentes + competitividad de precio."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class SourceOut(BaseModel):
    slug: str
    display_name: str | None
    kind: str
    status: str
    tos_risk_note: str | None

    #: Publicaciones vigentes de esta fuente en la base.
    listing_count: int
    #: Productos (clusters) en los que esta fuente tiene al menos una publicacion.
    product_count: int
    #: Productos en los que esta fuente tiene la publicacion mas barata.
    cheapest_count: int
    #: `cheapest_count / product_count`, 0..1. None si la fuente no tiene productos
    #: comparables todavia (una sola fuente en un cluster no prueba nada).
    win_rate: float | None

    last_success_at: datetime | None
    last_error: str | None


class SourcesResponse(BaseModel):
    #: Ordenadas por `win_rate` descendente: las tiendas que mas seguido tienen el
    #: mejor precio van primero.
    items: list[SourceOut]

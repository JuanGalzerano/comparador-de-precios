"""Punto de entrada de la API.

    uvicorn app.main:app --reload
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api.routers import auth, favorites, health, products, search, sources
from app.config import settings


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        description=(
            "Backend de Cotejo: agrupa publicaciones del mismo producto y las ordena por "
            "un score compuesto (precio final con envio, cuotas, reputacion, opiniones, "
            "garantia)."
        ),
        docs_url="/docs",
        openapi_url="/openapi.json",
    )

    # El frontend Next.js vive en otro origen y consume esta API por REST.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router)
    app.include_router(search.router)
    app.include_router(products.router)
    app.include_router(auth.router)
    app.include_router(favorites.router)
    app.include_router(sources.router)

    # TODO: montar aca los routers que faltan a medida que se implementen:
    #   - /ofertas (precio actual vs. mediana de 90 dias, sobre `price_history`)
    #   - /para-vos (recomendaciones sobre `user_event`, solo con consentimiento)
    #   - /admin (salud de `retailer_source`, cola de revision de `product_match`)

    return app


app = create_app()

"""`/health` — readiness de la API.

Chequea que el proceso este vivo Y que Postgres responda: sin base, la API no puede
servir nada util, asi que no tiene sentido reportar 200.
"""

from __future__ import annotations

from fastapi import APIRouter, Response, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app import __version__
from app.api.deps import DbSession
from app.config import settings
from app.services.maintenance import storage_status

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: str
    env: str
    version: str
    database: str


class StorageResponse(BaseModel):
    """Espacio usado vs. cuota del plan. Sirve para no enterarse de golpe."""

    used_mb: float
    quota_mb: int
    used_percent: float
    products: int
    listings: int
    price_points: int
    #: `True` cuando la próxima corrida de mantenimiento va a borrar productos fríos.
    evicting: bool
    #: `True` cuando ya se dejó de guardar lo que se trae en vivo (modo degradado).
    read_only: bool


@router.get("/health", response_model=HealthResponse)
def health(db: DbSession, response: Response) -> HealthResponse:
    try:
        db.execute(text("SELECT 1"))
        database = "ok"
    except SQLAlchemyError as exc:  # pragma: no cover - depende del entorno
        database = f"unreachable: {type(exc).__name__}"
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return HealthResponse(
        status="ok" if database == "ok" else "degraded",
        env=settings.cotejo_env,
        version=__version__,
        database=database,
    )


@router.get("/health/storage", response_model=StorageResponse)
def storage(db: DbSession) -> StorageResponse:
    """Cuánto espacio queda antes de que el caché empiece a reemplazar.

    La base es un caché de lo que la gente busca, así que llenarse es un estado normal,
    no una falla: a partir del 75% se borra lo frío y a partir del 90% se sirve todo en
    vivo sin guardar. Este endpoint es para verlo venir.
    """
    status_ = storage_status(db)
    return StorageResponse(
        used_mb=round(status_.used_bytes / 1_048_576, 2),
        quota_mb=settings.storage_quota_mb,
        used_percent=status_.used_percent,
        products=status_.products,
        listings=status_.listings,
        price_points=status_.price_points,
        evicting=status_.should_evict,
        read_only=status_.should_stop_writing,
    )

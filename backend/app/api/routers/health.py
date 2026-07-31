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

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: str
    env: str
    version: str
    database: str


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

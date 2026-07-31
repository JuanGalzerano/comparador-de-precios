"""Engine, sessionmaker y dependencia `get_db` de FastAPI.

SQLAlchemy sincrono (psycopg2) a proposito: el mismo codigo de acceso a datos lo van a
reusar los workers de Celery, que son sincronos. FastAPI corre los endpoints `def` en un
threadpool, asi que no bloquea el event loop.
"""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings

engine = create_engine(
    settings.database_url,
    echo=settings.sql_echo,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    pool_pre_ping=True,
    future=True,
)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
    class_=Session,
)


def get_db() -> Iterator[Session]:
    """Dependencia FastAPI: una sesion por request, siempre cerrada."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

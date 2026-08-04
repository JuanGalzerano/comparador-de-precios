"""Engine, sessionmaker y dependencia `get_db` de FastAPI.

SQLAlchemy sincrono (psycopg2) a proposito: el mismo codigo de acceso a datos lo van a
reusar los workers de Celery, que son sincronos. FastAPI corre los endpoints `def` en un
threadpool, asi que no bloquea el event loop.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings

_engine_kwargs: dict[str, Any] = dict(
    echo=settings.sql_echo,
    pool_pre_ping=True,
    future=True,
)

if settings.uses_sqlite:
    # SQLite no tiene pool de conexiones a un servidor (es un archivo), asi que
    # `pool_size`/`max_overflow` no aplican. `timeout` es lo que evita el
    # "database is locked" cuando la ingesta programada escribe mientras la API lee:
    # sin esto el default es 5 segundos y despues error.
    _engine_kwargs["connect_args"] = {"timeout": 30}
else:
    _engine_kwargs["pool_size"] = settings.db_pool_size
    _engine_kwargs["max_overflow"] = settings.db_max_overflow

engine = create_engine(settings.database_url, **_engine_kwargs)

if settings.uses_sqlite:

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_connection, _connection_record) -> None:  # type: ignore[no-untyped-def]
        """WAL: permite leer mientras se escribe.

        Con el journal por defecto (`DELETE`) un escritor bloquea a todos los lectores,
        asi que una ingesta programada corriendo en paralelo con la API hace que las
        busquedas devuelvan "database is locked". Solo aplica a SQLite (desarrollo);
        Postgres ya tiene MVCC.
        """
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()

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

"""Entorno de Alembic para Cotejo.

Dos cosas importantes:

1. La URL de la base sale de `DATABASE_URL` (env var / `.env`), NUNCA de `alembic.ini`.
   `alembic.ini` se commitea; las credenciales no.

2. `target_metadata` es `app.models.Base.metadata`, y se importa `app.models` completo:
   si un modelo nuevo no esta re-exportado en `app/models/__init__.py`, autogenerate no
   lo ve y llega a proponer un DROP de la tabla.
"""

from __future__ import annotations

import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

# `backend/` en el path para poder correr alembic desde cualquier directorio.
BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.config import settings  # noqa: E402
from app.models import Base  # noqa: E402  (importa y registra TODAS las tablas)

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# `%` se escapa: configparser lo interpreta como interpolacion y una password que lo
# contenga reventaria el arranque.
config.set_main_option("sqlalchemy.url", settings.database_url.replace("%", "%%"))

target_metadata = Base.metadata


def _include_object(obj, name, type_, reflected, compare_to) -> bool:
    """Filtra objetos que Alembic no debe gestionar.

    Por ahora no hay ninguno; el hook queda listo para cuando aparezcan (vistas
    materializadas, objetos creados por extensiones como `pg_trgm`, particiones).
    """
    return True


def run_migrations_offline() -> None:
    """Genera el SQL sin conectarse (`alembic upgrade head --sql`)."""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        # Sin esto Alembic no detecta cambios de tipo ni de server_default.
        compare_type=True,
        compare_server_default=True,
        include_object=_include_object,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Corre las migraciones contra una conexion real."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
            include_object=_include_object,
            # DDL transaccional por migracion: en Postgres, una que falla no deja el
            # schema a medio aplicar.
            transaction_per_migration=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

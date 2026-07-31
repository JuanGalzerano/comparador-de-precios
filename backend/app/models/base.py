"""Base declarativa, tipos reusables y mixins del schema.

Convenciones:
- Nombres de constraints explicitos (`naming_convention`) para que Alembic genere
  migraciones estables y reversibles (sin esto los nombres autogenerados por Postgres
  cambian entre entornos y `downgrade()` rompe).
- Dinero en `Numeric(14, 2)`: nunca float. En ARS 14 digitos cubre de sobra
  (un auto en el mock son ~$15.900.000).
- Timestamps siempre `timezone=True` y en UTC.
"""

from __future__ import annotations

import enum
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    DateTime,
    Enum as SAEnum,
    Integer,
    MetaData,
    Numeric,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


# --- Tipos reusables -------------------------------------------------------

#: JSONB en Postgres (indexable, operadores `->>`/`@>`); JSON plano en SQLite para
#: que los tests puedan correr sin levantar Postgres.
JSONBType = JSONB().with_variant(JSON(), "sqlite")

#: Tipo monetario del proyecto. `Numeric` -> `decimal.Decimal` en Python.
Money = Numeric(14, 2)

#: Timestamp con zona horaria (todo se guarda en UTC).
TZDateTime = DateTime(timezone=True)

#: PK/FK de 64 bits. `listing`, `price_history` y `user_event` crecen rapido
#: (una fila de `price_history` por listing por corrida de ingesta), asi que ningun id
#: del schema es INTEGER. La variante SQLite existe porque SQLite solo autoincrementa
#: sobre `INTEGER PRIMARY KEY`.
BigId = BigInteger().with_variant(Integer(), "sqlite")


def pg_enum(enum_cls: type[enum.Enum], name: str) -> SAEnum:
    """ENUM de Postgres que guarda `.value` (string legible) y no el nombre del miembro.

    Sin `values_callable`, SQLAlchemy persiste `"SEPA_FEED"` en vez de `"sepa_feed"`,
    que es lo que definio el plan y lo que espera el frontend.
    """
    return SAEnum(
        enum_cls,
        name=name,
        native_enum=True,
        validate_strings=True,
        values_callable=lambda e: [member.value for member in e],
    )


# --- Mixins ----------------------------------------------------------------


class TimestampMixin:
    """`created_at` / `updated_at` gestionados por la base."""

    created_at: Mapped[datetime] = mapped_column(
        TZDateTime, server_default=func.now(), nullable=False, sort_order=100
    )
    updated_at: Mapped[datetime] = mapped_column(
        TZDateTime,
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
        sort_order=101,
    )


class IdMixin:
    """PK entera autoincremental (`BIGSERIAL` en Postgres).

    `sort_order` negativo para que `id` quede primero en el DDL: por defecto SQLAlchemy
    pone las columnas de mixin despues de las propias de la clase.
    """

    id: Mapped[int] = mapped_column(
        BigId, primary_key=True, autoincrement=True, sort_order=-100
    )


JsonDict = dict[str, Any]

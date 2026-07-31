"""Enums compartidos entre el schema (SQLAlchemy) y los adapters.

Viven fuera de `app.models` para que `app.adapters` pueda tipar sus DTOs sin importar
el ORM (un adapter tiene que poder correr en un proceso que no toca la base, p.ej. un
spider de Scrapy que solo emite `NormalizedListingInput`).

Todos heredan de `str` para serializar directo a JSON y para que el valor guardado en
Postgres sea el string legible (`"api"`, no `"API"`). En SQLAlchemy siempre se declaran
con `values_callable` (ver `app/models/base.py: pg_enum`) para que el tipo ENUM de PG
use `.value` y no el nombre del miembro.
"""

from __future__ import annotations

import enum


class SourceKind(str, enum.Enum):
    """Como se obtienen los datos de una fuente. Determina que adapter la atiende."""

    API = "api"  # API publica oficial y sancionada (MercadoLibre)
    VTEX = "vtex"  # endpoint semi-publico de catalogo VTEX (Fravega, Cetrogar)
    SEPA_FEED = "sepa_feed"  # dumps ZIP diarios de Precios Claros / SEPA
    SCRAPER = "scraper"  # spider Scrapy propio


class SourceStatus(str, enum.Enum):
    """Gate operativo/legal de una fuente. El worker de ingesta solo corre las ACTIVE."""

    ACTIVE = "active"
    DISABLED = "disabled"
    EXPERIMENTAL = "experimental"
    BLOCKED_TOS_REVIEW = "blocked_tos_review"


class MatchMethod(str, enum.Enum):
    """Como se vinculo una publicacion con un producto canonico."""

    CATALOG_ID = "catalog_id"  # deterministico (catalog_product_id / EAN / SKU)
    FUZZY = "fuzzy"  # similitud de titulos + overlap de atributos
    EMBEDDING = "embedding"  # vectorial, para casos ambiguos
    MANUAL = "manual"  # resuelto a mano en el panel admin


class ItemCondition(str, enum.Enum):
    """Estado del item publicado.

    No estaba entre los campos con valores fijos del plan, pero `scoreOf()` y los filtros
    de la UI comparan contra `new`/`used` literales, asi que conviene un ENUM en vez de
    texto libre. `UNKNOWN` existe porque varios feeds (VTEX, SEPA) no informan condicion.
    """

    NEW = "new"
    USED = "used"
    REFURBISHED = "refurbished"
    UNKNOWN = "unknown"


class WarrantyType(str, enum.Enum):
    """Tipo de garantia, con los mismos valores que usa `scoreOf()` en el prototipo.

    El multiplicador del eje garantia sale directo de estos valores
    (`oficial` -> 1.0, `vendedor` -> 0.8, `sin` -> 0.0), por eso es ENUM y no texto libre.
    `UNKNOWN` = la fuente no informa (distinto de `SIN`, que es "informa que no hay").
    """

    OFICIAL = "oficial"
    VENDEDOR = "vendedor"
    SIN = "sin"
    UNKNOWN = "unknown"


# Niveles de reputacion de vendedor de MercadoLibre.
#
# NO es un ENUM de base a proposito: `listing.seller_level` es `String(32)` nullable porque
# cada retailer tiene (o no tiene) su propio esquema de reputacion y no queremos una
# migracion cada vez que aparece uno nuevo. Esta constante existe para que el normalizador
# de cada adapter mapee a estas claves cuando pueda: son las que espera `scoreOf()`
# (`platinum: 1, gold: 0.78, silver: 0.5, green: 0.3`, default 0.3 si no matchea).
SELLER_LEVELS: tuple[str, ...] = ("platinum", "gold", "silver", "green")

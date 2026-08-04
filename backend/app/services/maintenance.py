"""Mantenimiento del caché: retención, evicción y control de espacio.

La base de Cotejo es un **caché de lo que la gente busca** (ver `live_search.py`), no un
catálogo permanente. Un caché sin política de reemplazo no es un caché: crece hasta
llenarse y entonces deja de aceptar cosas nuevas, que es el peor estado posible — se
queda congelado con lo que se buscó primero, que no tiene por qué ser lo que se busca hoy.

Tres capas, de la más barata a la más agresiva:

1. **Retención del historial de precios** (`purge_price_history`). Es lo que más crece:
   una fila por publicación por cada cambio de precio, para siempre. La ficha de producto
   solo muestra los últimos 90 días, así que borrar más allá de esa ventana no saca nada
   que se vea.

2. **Evicción de productos fríos** (`evict_cold_products`). Borra lo que nadie mira.
   El criterio combina las dos señales que usa cualquier caché serio — **recencia** (hace
   cuánto que nadie lo ve) y **frecuencia** (cuántas veces se vio) — porque cada una sola
   se equivoca: por edad pura se borran clásicos que se buscan siempre, y por frecuencia
   pura nunca entra nada nuevo (el problema de "cache pollution"). Si mañana alguien busca
   algo que se borró, `live_search` lo trae de nuevo en ~2 segundos.

3. **Freno por cuota** (`storage_status` + `should_persist`). Si la base se acerca al
   límite del plan contratado, se deja de guardar y el sitio pasa a servir todo en vivo.
   Es una degradación, no una caída: sigue funcionando, más lento.

Nada de esto toca lo que un usuario guardó explícitamente en sus favoritos.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session

from app.config import settings
from app.models.listing import Listing
from app.models.price_history import PriceHistory
from app.models.product import Product
from app.models.product_match import ProductMatch
from app.models.saved_product import SavedProduct

logger = logging.getLogger(__name__)

#: Ventana de historial que la UI muestra. Borrar más viejo que esto no saca nada visible.
PRICE_HISTORY_DAYS = 90

#: Un producto no se considera para evicción antes de esto, ni aunque no lo haya visto
#: nadie: recién ingestado todavía no tuvo la oportunidad de que lo busquen.
MIN_AGE_DAYS = 7

#: Sin accesos en este tiempo, un producto es candidato a borrarse.
COLD_AFTER_DAYS = 30

#: Un producto con al menos estos accesos sobrevive aunque esté frío: se busca lo
#: suficiente como para que valga la pena tenerlo cacheado.
POPULAR_ACCESS_COUNT = 5

#: Porcentaje de la cuota a partir del cual se deja de guardar lo que se trae en vivo.
STOP_WRITING_AT_PERCENT = 90.0

#: Porcentaje a partir del cual la evicción automática se dispara sola.
EVICT_AT_PERCENT = 75.0


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Capa 3 — espacio disponible
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StorageStatus:
    used_bytes: int
    quota_bytes: int
    products: int
    listings: int
    price_points: int

    @property
    def used_percent(self) -> float:
        if self.quota_bytes <= 0:
            return 0.0
        return round(self.used_bytes / self.quota_bytes * 100, 2)

    @property
    def should_evict(self) -> bool:
        return self.used_percent >= EVICT_AT_PERCENT

    @property
    def should_stop_writing(self) -> bool:
        return self.used_percent >= STOP_WRITING_AT_PERCENT

    def __str__(self) -> str:
        return (
            f"{self.used_bytes / 1_048_576:.1f} MB de "
            f"{self.quota_bytes / 1_048_576:.0f} MB ({self.used_percent}%) — "
            f"{self.products} productos, {self.listings} publicaciones, "
            f"{self.price_points} puntos de historial"
        )


def database_size_bytes(db: Session) -> int:
    """Tamaño real de la base, en bytes. Funciona en SQLite y en Postgres."""
    if settings.uses_sqlite:
        page_count = db.execute(text("PRAGMA page_count")).scalar_one()
        page_size = db.execute(text("PRAGMA page_size")).scalar_one()
        return int(page_count) * int(page_size)
    return int(db.execute(text("SELECT pg_database_size(current_database())")).scalar_one())


def storage_status(db: Session) -> StorageStatus:
    return StorageStatus(
        used_bytes=database_size_bytes(db),
        quota_bytes=settings.storage_quota_bytes,
        products=db.scalar(select(func.count(Product.id))) or 0,
        listings=db.scalar(select(func.count(Listing.id))) or 0,
        price_points=db.scalar(select(func.count(PriceHistory.id))) or 0,
    )


def should_persist(db: Session) -> bool:
    """`False` cuando la base está cerca de la cuota: se sirve en vivo sin guardar."""
    status = storage_status(db)
    if status.should_stop_writing:
        logger.warning(
            "almacenamiento al %.1f%% de la cuota: no se guarda lo traido en vivo (%s)",
            status.used_percent,
            status,
        )
        return False
    return True


# ---------------------------------------------------------------------------
# Capa 1 — retención del historial
# ---------------------------------------------------------------------------


def purge_price_history(db: Session, *, days: int = PRICE_HISTORY_DAYS) -> int:
    """Borra los puntos de historial más viejos que `days`. Devuelve cuántos borró.

    Se conserva SIEMPRE el punto más reciente de cada publicación aunque sea viejo: es el
    precio con el que se compara el próximo cambio, y sin él una publicación que no varía
    hace meses perdería su serie entera.
    """
    cutoff = _utcnow() - timedelta(days=days)

    newest_per_listing = (
        select(func.max(PriceHistory.id))
        .group_by(PriceHistory.listing_id)
        .scalar_subquery()
    )

    result = db.execute(
        delete(PriceHistory).where(
            PriceHistory.captured_at < cutoff,
            PriceHistory.id.not_in(newest_per_listing),
        )
    )
    db.commit()
    deleted = result.rowcount or 0
    if deleted:
        logger.info("retención: %s puntos de historial anteriores a %s", deleted, cutoff.date())
    return deleted


# ---------------------------------------------------------------------------
# Capa 2 — evicción de lo frío
# ---------------------------------------------------------------------------


def touch_products(db: Session, product_ids: list[int]) -> None:
    """Registra que estos productos se usaron. Barato: un solo UPDATE.

    Se llama desde `/search` y desde la ficha de producto. Sin esto no hay forma de
    distinguir un producto que se busca todos los días de uno que nadie miró nunca, y la
    evicción tendría que borrar por edad — que es exactamente lo que no queremos.
    """
    if not product_ids:
        return
    db.execute(
        Product.__table__.update()
        .where(Product.id.in_(product_ids))
        .values(
            last_accessed_at=_utcnow(),
            access_count=Product.__table__.c.access_count + 1,
        )
    )
    db.commit()


@dataclass(frozen=True)
class EvictionResult:
    products_deleted: int = 0
    listings_deleted: int = 0

    def __str__(self) -> str:
        return (
            f"evicción: {self.products_deleted} productos y "
            f"{self.listings_deleted} publicaciones"
        )


def _cold_product_ids(
    db: Session,
    *,
    limit: int,
    cold_after_days: int,
    min_age_days: int,
    popular_access_count: int,
) -> list[int]:
    """Los productos más prescindibles, peores primero.

    Candidato = suficientemente viejo Y frío Y no popular Y que nadie guardó en favoritos.
    El orden pone primero lo que menos se usó y, a igual uso, lo más antiguo — o sea, la
    basura primero.
    """
    now = _utcnow()
    created_cutoff = now - timedelta(days=min_age_days)
    cold_cutoff = now - timedelta(days=cold_after_days)

    saved = select(SavedProduct.product_id).scalar_subquery()

    stmt = (
        select(Product.id)
        .where(
            Product.created_at < created_cutoff,
            Product.access_count < popular_access_count,
            # Nunca accedido, o accedido hace mucho.
            (Product.last_accessed_at.is_(None)) | (Product.last_accessed_at < cold_cutoff),
            # Lo que alguien guardó explícitamente no es basura: nunca se toca.
            Product.id.not_in(saved),
        )
        .order_by(
            Product.access_count.asc(),
            Product.last_accessed_at.asc().nulls_first(),
            Product.created_at.asc(),
        )
        .limit(limit)
    )
    return list(db.scalars(stmt))


def evict_cold_products(
    db: Session,
    *,
    limit: int = 500,
    cold_after_days: int = COLD_AFTER_DAYS,
    min_age_days: int = MIN_AGE_DAYS,
    popular_access_count: int = POPULAR_ACCESS_COUNT,
) -> EvictionResult:
    """Borra hasta `limit` productos fríos, con sus publicaciones e historial.

    No es destructivo en el sentido que importa: lo borrado se puede volver a traer de las
    tiendas en ~2 segundos la próxima vez que alguien lo busque.
    """
    ids = _cold_product_ids(
        db,
        limit=limit,
        cold_after_days=cold_after_days,
        min_age_days=min_age_days,
        popular_access_count=popular_access_count,
    )
    if not ids:
        return EvictionResult()

    listing_ids = list(
        db.scalars(select(Listing.id).where(Listing.product_id.in_(ids)))
    )

    # Orden explícito: los hijos primero. `price_history` y `product_match` tienen
    # ON DELETE CASCADE, pero en SQLite las foreign keys no se fuerzan por defecto, así
    # que confiar en el cascade haría que el borrado se comporte distinto según el motor.
    if listing_ids:
        db.execute(delete(PriceHistory).where(PriceHistory.listing_id.in_(listing_ids)))
        db.execute(delete(ProductMatch).where(ProductMatch.listing_id.in_(listing_ids)))
        db.execute(delete(Listing).where(Listing.id.in_(listing_ids)))
    db.execute(delete(ProductMatch).where(ProductMatch.product_id.in_(ids)))
    db.execute(delete(Product).where(Product.id.in_(ids)))
    db.commit()

    result = EvictionResult(products_deleted=len(ids), listings_deleted=len(listing_ids))
    logger.info("%s", result)
    return result


# ---------------------------------------------------------------------------
# Orquestación
# ---------------------------------------------------------------------------


@dataclass
class MaintenanceReport:
    before: StorageStatus
    after: StorageStatus
    history_deleted: int = 0
    eviction: EvictionResult = EvictionResult()

    def __str__(self) -> str:
        return (
            f"antes: {self.before}\n"
            f"  historial borrado: {self.history_deleted}\n"
            f"  {self.eviction}\n"
            f"despues: {self.after}"
        )


def run_maintenance(
    db: Session,
    *,
    force_evict: bool = False,
    evict_limit: int = 500,
) -> MaintenanceReport:
    """Corre las tres capas en orden. Pensado para un cron diario.

    La retención corre siempre (es barata y nunca borra nada visible). La evicción solo
    si la base pasó el umbral de espacio, o si se la fuerza a mano.
    """
    before = storage_status(db)
    history_deleted = purge_price_history(db)

    eviction = EvictionResult()
    status = storage_status(db)
    if force_evict or status.should_evict:
        eviction = evict_cold_products(db, limit=evict_limit)
        if settings.uses_sqlite:
            # Sin esto SQLite no devuelve el espacio al sistema de archivos: las páginas
            # quedan marcadas como libres pero el archivo sigue igual de grande.
            db.commit()
            db.execute(text("VACUUM"))

    return MaintenanceReport(
        before=before,
        after=storage_status(db),
        history_deleted=history_deleted,
        eviction=eviction,
    )

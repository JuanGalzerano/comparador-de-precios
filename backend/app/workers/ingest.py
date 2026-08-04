"""Worker de ingesta: corre UNA fuente (`retailer_source`) y hace upsert en `listing`.

Implementa el contrato documentado en `app/workers/__init__.py`, para una sola fuente por
llamada (el orquestador que itera *todas* las `retailer_source` con `status='active'` y las
encola en Celery es un wrapper trivial futuro, fuera de esta tarea):

    1. lee la fila `retailer_source` por `slug`;
    2. `adapter = build_adapter(source)`;
    3. `for raw in adapter.fetch_listings(request): ...` (`SearchQuery` o `RefreshRequest`,
       segun lo que pase el caller/CLI);
    4. `adapter.normalize(raw)` -> `NormalizedListingInput`;
    5. upsert en `listing` por `(retailer_source_id, external_id)`;
    6. `price_history` SOLO si `price`/`shipping_cost` cambiaron respecto del ultimo
       snapshot (o es la primera vez que se ve la publicacion);
    7. `last_run_at` siempre; `last_success_at` si la corrida no aborto por una excepcion
       de ADAPTER (`AdapterError` y subclases); `last_error` con un resumen; un item que
       falla al normalizar/persistir se loggea y se saltea, no aborta el batch.
       `BlockedBySource` ademas pasa la fuente a `status='blocked_tos_review'`.
    8. `listing.product_id` queda `NULL` siempre (matching es un paso aparte).

No agrega Celery/Redis: se usa una `Session` de SQLAlchemy sincrona directa (mismo patron
que `app/db.py`), para que este mismo codigo lo pueda invocar mas adelante un task de
Celery sin cambios.
"""

from __future__ import annotations

import argparse
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.adapters.errors import AdapterError, BlockedBySource, NormalizationError
from app.adapters.registry import build_adapter
from app.adapters.types import (
    FetchRequest,
    NormalizedListingInput,
    RefreshRequest,
    SearchQuery,
)
from app.enums import SourceStatus
from app.matching.matcher import match_listings
from app.models.listing import Listing
from app.models.price_history import PriceHistory
from app.models.retailer_source import RetailerSource

logger = logging.getLogger(__name__)

__all__ = [
    "IngestRunResult",
    "SourceNotConfigured",
    "ingest_source",
    "run_ingest",
    "main",
]


class SourceNotConfigured(LookupError):
    """No existe una fila `retailer_source` para ese slug.

    Es un error de configuracion/seed (falta el INSERT en `retailer_source`), no un error
    de datos de la fuente: la ingesta no puede improvisar una fila que no existe.
    """


@dataclass
class IngestRunResult:
    """Resumen de una corrida, para logs/CLI y para que un test pueda hacer asserts."""

    source_slug: str
    inserted: int = 0
    updated: int = 0
    price_points_added: int = 0
    #: Mensajes de items que fallaron (normalizacion o persistencia); no incluye fallas de
    #: adapter completo (esas se propagan como excepcion, ver `ingest_source`).
    item_errors: list[str] = field(default_factory=list)

    @property
    def processed(self) -> int:
        return self.inserted + self.updated

    @property
    def has_item_errors(self) -> bool:
        return bool(self.item_errors)

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return (
            f"<IngestRunResult source={self.source_slug!r} inserted={self.inserted} "
            f"updated={self.updated} price_points={self.price_points_added} "
            f"errors={len(self.item_errors)}>"
        )


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _load_source(db: Session, source_slug: str) -> RetailerSource:
    source = db.query(RetailerSource).filter(RetailerSource.slug == source_slug).first()
    if source is None:
        raise SourceNotConfigured(
            f"no existe retailer_source con slug={source_slug!r}; sembrala (seed/migracion) "
            "antes de correr la ingesta"
        )
    return source


def _fit(value: str | None, max_length: int) -> str | None:
    """Trunca al largo de la columna.

    SQLite ignora los largos de `VARCHAR(n)`; Postgres levanta
    `StringDataRightTruncation` y aborta la transaccion. Como todo el desarrollo corre
    contra SQLite, un titulo largo de una tienda nueva solo se manifestaria en
    produccion. Truncar un titulo es preferible a perder la publicacion entera.
    """
    if value is None:
        return None
    return value if len(value) <= max_length else value[:max_length]


def _listing_fields(normalized: NormalizedListingInput) -> dict[str, Any]:
    """Campos de `listing` que vienen del adapter (todo menos las claves de upsert).

    `product_id` no aparece aca a proposito: el matching es un paso aparte (punto 8 del
    contrato) y nunca lo toca este worker, ni al insertar ni al actualizar.
    """
    hint = normalized.product_hint
    return {
        "title": _fit(normalized.title, 512),
        "permalink": normalized.permalink,
        "condition": normalized.condition,
        "price": normalized.price,
        "shipping_cost": normalized.shipping_cost,
        "installments_qty": normalized.installments_qty,
        "installments_amount": normalized.installments_amount,
        "interest_free": normalized.interest_free,
        "seller_name": _fit(normalized.seller_name, 256),
        "seller_id": _fit(normalized.seller_id, 64),
        "seller_level": _fit(normalized.seller_level, 32),
        "seller_sales": normalized.seller_sales,
        "official_store": _fit(normalized.official_store, 128),
        "fulfillment": normalized.fulfillment,
        "rating": normalized.rating,
        "reviews_count": normalized.reviews_count,
        "warranty_months": normalized.warranty_months,
        "warranty_type": normalized.warranty_type,
        # El id de catalogo de la fuente es el mejor dato de matching que existe; antes
        # el adapter lo extraia y se descartaba aca, y la via deterministica del matcher
        # quedaba muerta.
        "catalog_product_id": _fit(hint.catalog_product_id if hint else None, 64),
        "fetched_at": normalized.fetched_at,
    }


def _upsert_listing(
    db: Session,
    source: RetailerSource,
    normalized: NormalizedListingInput,
    result: IngestRunResult,
) -> None:
    """Upsert por `(retailer_source_id, external_id)` + `price_history` condicional.

    Decision de diseno sobre "cambio el precio": se compara `Decimal` con `!=` directo
    (sin redondear a mano). `Decimal("100000") == Decimal("100000.00")` ya es `True` en
    Python -- la igualdad de `Decimal` es por VALOR, no por representacion/escala -- asi
    que no hace falta normalizar escala antes de comparar. `None` vs. `Decimal(0)` SI se
    trata como cambio real (pasar de "la fuente no informa envio" a "envio confirmado a
    $0" es informacion nueva, no ruido).
    """
    existing = (
        db.query(Listing)
        .filter(
            Listing.retailer_source_id == source.id,
            Listing.external_id == normalized.external_id,
        )
        .first()
    )
    fields = _listing_fields(normalized)

    if existing is None:
        listing = Listing(
            retailer_source_id=source.id,
            product_id=None,
            external_id=normalized.external_id,
            **fields,
        )
        db.add(listing)
        db.flush()
        # Primera vez que se ve la publicacion: siempre hay un primer punto de historial.
        db.add(
            PriceHistory(
                listing_id=listing.id,
                price=normalized.price,
                shipping_cost=normalized.shipping_cost,
            )
        )
        result.inserted += 1
        result.price_points_added += 1
        return

    old_price = existing.price
    old_shipping = existing.shipping_cost
    for key, value in fields.items():
        setattr(existing, key, value)
    db.flush()
    result.updated += 1

    if old_price != normalized.price or old_shipping != normalized.shipping_cost:
        db.add(
            PriceHistory(
                listing_id=existing.id,
                price=normalized.price,
                shipping_cost=normalized.shipping_cost,
            )
        )
        result.price_points_added += 1


def run_ingest(
    db: Session, source: RetailerSource, request: FetchRequest
) -> IngestRunResult:
    """Corre la ingesta para una fila de `retailer_source` YA CARGADA.

    Separado de `ingest_source` para que un caller que ya tiene el ORM object en mano
    (p.ej. un futuro loop que itera todas las fuentes activas) no pague un segundo query.
    """
    adapter = build_adapter(source)
    result = IngestRunResult(source_slug=source.slug)

    try:
        for raw in adapter.fetch_listings(request):
            try:
                normalized = adapter.normalize(raw)
                if normalized.currency != "ARS":
                    # El schema de `listing` es mono-moneda (ver `NormalizedListingInput.
                    # currency` y `app/models/listing.py`): rechazar en vez de guardar un
                    # numero incomparable contra el resto de la tabla.
                    raise ValueError(
                        f"moneda no soportada {normalized.currency!r} para "
                        f"external_id={normalized.external_id!r} (listing es ARS-only)"
                    )
                _upsert_listing(db, source, normalized, result)
                db.commit()
            except (NormalizationError, ValueError, SQLAlchemyError) as exc:
                db.rollback()
                origin = getattr(raw, "origin_ref", None)
                message = f"{exc} (origin_ref={origin!r})"
                logger.warning(
                    "ingesta[%s]: item descartado: %s", source.slug, message
                )
                result.item_errors.append(message)
                continue
    except BlockedBySource as exc:
        # No reintentable: se escala a revision humana y NO se marca last_success_at.
        now = _utcnow()
        source.last_run_at = now
        source.last_error = str(exc)
        source.status = SourceStatus.BLOCKED_TOS_REVIEW
        db.add(source)
        db.commit()
        raise
    except AdapterError as exc:
        # SourceUnavailable/RateLimited/AuthenticationError/UnsupportedFetchMode: la
        # corrida entera fallo, se propaga al caller (Celery decidira reintentar).
        now = _utcnow()
        source.last_run_at = now
        source.last_error = str(exc)
        db.add(source)
        db.commit()
        raise

    now = _utcnow()
    source.last_run_at = now
    source.last_success_at = now
    if result.item_errors:
        preview = "; ".join(result.item_errors[:5])
        source.last_error = (
            f"{len(result.item_errors)} item(s) fallaron durante la corrida "
            f"(batch completo, no reintentable automaticamente): {preview}"
        )
    else:
        source.last_error = None
    # Una corrida exitosa levanta el bloqueo: `BlockedBySource` marca la fuente como
    # `BLOCKED_TOS_REVIEW`, y ML devuelve 403 tanto si te bloquearon como si se te
    # vencio el token (dura 6 horas). Sin este reset, un token vencido dejaba a la
    # fuente marcada para siempre y `/como-funciona` publicaba "Pausada por revision de
    # terminos" aunque la ingesta ya estuviera funcionando de nuevo.
    if source.status == SourceStatus.BLOCKED_TOS_REVIEW:
        logger.info(
            "ingesta[%s]: corrida exitosa, se reactiva la fuente (estaba en %s)",
            source.slug,
            source.status.value,
        )
        source.status = SourceStatus.ACTIVE
    db.add(source)
    db.commit()
    return result


def ingest_source(
    db: Session, source_slug: str, request: FetchRequest
) -> IngestRunResult:
    """Punto de entrada por slug: carga `retailer_source`, arma el adapter y corre.

    Levanta `SourceNotConfigured` si el slug no tiene fila (nunca se crea una fuente
    implicitamente: eso es responsabilidad del seed/migracion, no del worker).
    """
    source = _load_source(db, source_slug)
    return run_ingest(db, source, request)


# ---------------------------------------------------------------------------
# CLI: python -m app.workers.ingest <source_slug> [--term ...] [--refresh]
# ---------------------------------------------------------------------------


def _build_cli_request(db: Session, source: RetailerSource, args: argparse.Namespace) -> FetchRequest:
    if args.refresh:
        external_ids = [
            row[0]
            for row in db.query(Listing.external_id)
            .filter(Listing.retailer_source_id == source.id)
            .all()
        ]
        if not external_ids:
            raise SystemExit(
                f"no hay listings existentes para {source.slug!r}; nada que refrescar "
                "(corre sin --refresh primero para poblar la fuente)"
            )
        return RefreshRequest(external_ids=external_ids)
    return SearchQuery(
        term=args.term, category=args.category, max_results=args.max_results
    )


def main(argv: list[str] | None = None) -> int:
    # Import local: evita que un `import app.workers.ingest` para usar `ingest_source`
    # en un proceso sin `.env` de base configurada dispare la creacion del engine.
    from app.db import SessionLocal

    parser = argparse.ArgumentParser(
        prog="python -m app.workers.ingest",
        description="Corre una ingesta puntual contra una fuente (`retailer_source.slug`).",
    )
    parser.add_argument("source_slug", help="ej. 'mercadolibre'")
    parser.add_argument("--term", default=None, help="Termino de busqueda (modo search)")
    parser.add_argument(
        "--category", default=None, help="Categoria en el vocabulario de la fuente"
    )
    parser.add_argument("--max-results", type=int, default=None, dest="max_results")
    parser.add_argument(
        "--refresh",
        action="store_true",
        help=(
            "Modo refresh: relee los external_id ya existentes de esta fuente "
            "(alimenta price_history) en vez de buscar un termino nuevo"
        ),
    )
    parser.add_argument(
        "--no-match",
        action="store_true",
        help=(
            "No correr el matcher al terminar. Por defecto la ingesta agrupa las "
            "publicaciones nuevas en productos (`python -m app.workers.match`)."
        ),
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO)

    match_stats = None
    db = SessionLocal()
    try:
        source = _load_source(db, args.source_slug)
        request = _build_cli_request(db, source, args)
        result = run_ingest(db, source, request)
        if not args.no_match:
            match_stats = match_listings(db)
    except SourceNotConfigured as exc:
        print(f"error: {exc}")
        return 1
    except AdapterError as exc:
        print(f"error de adapter (corrida abortada): {exc}")
        return 1
    finally:
        db.close()

    print(
        f"fuente={result.source_slug} insertados={result.inserted} "
        f"actualizados={result.updated} price_history_nuevos={result.price_points_added} "
        f"errores_de_item={len(result.item_errors)}"
    )
    if match_stats is not None:
        print(f"matching: {match_stats}")
    for message in result.item_errors:
        print(f"  - {message}")
    return 0 if not result.item_errors else 2


if __name__ == "__main__":
    raise SystemExit(main())

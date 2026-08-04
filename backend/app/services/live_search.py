"""Búsqueda en vivo contra las tiendas, con persistencia.

El modelo de datos de Cotejo no aspira a tener "todos los productos del mundo": eso no
entra en ningún plan gratis y además envejece solo. La base es un **caché de lo que la
gente realmente busca**: si alguien busca algo que no está, se les pregunta a las tiendas
en el momento, se guarda, y la próxima persona que busque lo mismo lo ve instantáneo.

Medido contra las APIs reales: consultar las tres tiendas en paralelo tarda entre 1,5 y
2,2 segundos. Secuencial serían más de 4.

Dos fases separadas a propósito:

1. **Red, en paralelo, sin tocar la base.** Una `Session` de SQLAlchemy no es thread-safe,
   así que los hilos solo hacen HTTP y devuelven DTOs (`NormalizedListingInput`).
2. **Escritura, en el hilo principal.** Reusa el mismo `_upsert_listing` que la ingesta
   programada, así una publicación traída en vivo y una traída por el worker son
   indistinguibles en la base (misma clave natural, mismo `price_history`).

Lo que este módulo NO hace: reemplazar al worker de ingesta. El worker sigue siendo quien
mantiene frescos los precios de lo que ya se conoce; esto solo cubre el hueco de "nadie
buscó esto todavía".
"""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.adapters.errors import AdapterError, NormalizationError
from app.adapters.registry import build_adapter
from app.adapters.types import FetchMode, NormalizedListingInput, SearchQuery
from app.enums import SourceStatus
from app.matching.matcher import match_listings
from app.models.retailer_source import RetailerSource
from app.services.maintenance import should_persist
from app.workers.ingest import IngestRunResult, _upsert_listing

logger = logging.getLogger(__name__)

#: Cuántas publicaciones se le piden a CADA tienda. Bajo a propósito: esto corre dentro
#: de un request web, no en un batch nocturno.
DEFAULT_PER_SOURCE = 12

#: Cuánto se espera a una tienda antes de seguir sin ella. El usuario está esperando la
#: página: es preferible mostrar dos tiendas de tres que hacerlo esperar de más.
DEFAULT_TIMEOUT_SECONDS = 6.0

#: Un término no se vuelve a consultar en vivo hasta pasado este tiempo. Sin esto, cada
#: F5 sobre una búsqueda popular dispara tres llamadas HTTP a las tiendas.
COOLDOWN_SECONDS = 900  # 15 minutos

#: `term normalizado -> monotonic() de la última consulta`. En memoria del proceso: con
#: varios workers cada uno tiene el suyo, lo cual es aceptable (el peor caso es consultar
#: una vez por worker). Si algún día hace falta compartirlo, va a Redis.
_last_fetch: dict[str, float] = {}


@dataclass
class LiveSearchResult:
    term: str
    inserted: int = 0
    updated: int = 0
    sources_ok: list[str] = field(default_factory=list)
    sources_failed: list[str] = field(default_factory=list)
    elapsed_ms: int = 0
    skipped_by_cooldown: bool = False
    #: La base está cerca de la cuota: se consultó igual, pero no se guardó nada.
    persisted: bool = True
    #: Lo que trajeron las tiendas. Solo se completa cuando `persisted` es `False`: ahí
    #: `/search` no puede leerlo de la base y tiene que servirlo desde acá.
    items: list[NormalizedListingInput] = field(default_factory=list)

    @property
    def found_anything(self) -> bool:
        return self.inserted > 0 or self.updated > 0

    def __str__(self) -> str:
        if self.skipped_by_cooldown:
            return f"live[{self.term!r}]: omitida (consultada hace poco)"
        return (
            f"live[{self.term!r}]: nuevas={self.inserted} actualizadas={self.updated} "
            f"ok={','.join(self.sources_ok) or '-'} "
            f"fallaron={','.join(self.sources_failed) or '-'} {self.elapsed_ms}ms"
        )


def _normalize_term(term: str) -> str:
    return " ".join(term.lower().split())


def should_fetch(term: str) -> bool:
    """`False` si este término ya se consultó hace menos de `COOLDOWN_SECONDS`."""
    key = _normalize_term(term)
    last = _last_fetch.get(key)
    return last is None or (time.monotonic() - last) >= COOLDOWN_SECONDS


def _fetch_one_source(
    source_id: int,
    slug: str,
    kind: str,
    config: dict,
    term: str,
    per_source: int,
) -> tuple[int, str, list[NormalizedListingInput], str | None]:
    """Consulta UNA tienda. Corre en un hilo: no puede tocar la base.

    Recibe los datos de la fuente por valor (no el objeto ORM) justamente para que no
    haya forma de tocar la `Session` desde acá.
    """
    from app.adapters.registry import resolve_adapter_class

    try:
        adapter_cls = resolve_adapter_class(slug, kind)  # type: ignore[arg-type]
        adapter = adapter_cls(source_slug=slug, config=config or {})
        query = SearchQuery(
            mode=FetchMode.SEARCH,
            term=term,
            max_results=per_source,
            page_size=per_source,
            enrich=False,  # los datos caros (reputación, reseñas) los trae el worker
        )
        normalized: list[NormalizedListingInput] = []
        for raw in adapter.search(query):
            try:
                item = adapter.normalize(raw)
            except NormalizationError as exc:
                logger.debug("live[%s]: item descartado: %s", slug, exc)
                continue
            if item.currency != "ARS":
                continue
            normalized.append(item)
        return source_id, slug, normalized, None
    except AdapterError as exc:
        return source_id, slug, [], str(exc)
    except Exception as exc:  # una tienda rota no puede tumbar la búsqueda entera
        return source_id, slug, [], f"{type(exc).__name__}: {exc}"


def fetch_live(
    db: Session,
    term: str,
    *,
    per_source: int = DEFAULT_PER_SOURCE,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    force: bool = False,
) -> LiveSearchResult:
    """Consulta las tiendas activas por `term`, guarda lo que llega y agrupa.

    Devuelve el resumen de la corrida. No levanta excepciones por fallas de una tienda:
    lo peor que puede pasar es que no se traiga nada y el usuario vea lo que ya había.
    """
    result = LiveSearchResult(term=term)
    clean = term.strip()
    if not clean:
        return result

    if not force and not should_fetch(clean):
        result.skipped_by_cooldown = True
        return result

    started = time.monotonic()
    _last_fetch[_normalize_term(clean)] = started

    sources = db.scalars(
        select(RetailerSource).where(RetailerSource.status == SourceStatus.ACTIVE)
    ).all()
    if not sources:
        return result

    # Snapshot de lo que los hilos necesitan, para no compartir objetos ORM entre hilos.
    specs = [(s.id, s.slug, s.kind, dict(s.config_json or {})) for s in sources]

    fetched: list[tuple[int, list[NormalizedListingInput]]] = []
    with ThreadPoolExecutor(max_workers=min(8, len(specs))) as pool:
        futures = {
            pool.submit(_fetch_one_source, sid, slug, kind, config, clean, per_source): slug
            for sid, slug, kind, config in specs
        }
        try:
            for future in as_completed(futures, timeout=timeout):
                source_id, slug, items, error = future.result()
                if error:
                    result.sources_failed.append(slug)
                    logger.warning("live[%s]: %s", slug, error)
                    continue
                result.sources_ok.append(slug)
                fetched.append((source_id, items))
        except TimeoutError:
            # Las tiendas que no contestaron a tiempo simplemente no aportan resultados.
            pendientes = [
                slug for future, slug in futures.items() if not future.done()
            ]
            result.sources_failed.extend(pendientes)
            logger.warning("live[%r]: timeout esperando a %s", clean, pendientes)

    if not fetched:
        result.elapsed_ms = int((time.monotonic() - started) * 1000)
        return result

    # --- Fase 2: escritura, en el hilo principal --------------------------------
    # Freno por cuota: si la base está llena, se devuelve lo que trajeron las tiendas
    # sin guardarlo. El sitio sigue funcionando (más lento, porque cada búsqueda vuelve
    # a salir a la red), en vez de dejar de encontrar cosas.
    if not should_persist(db):
        result.persisted = False
        result.items = [item for _, items in fetched for item in items]
        result.elapsed_ms = int((time.monotonic() - started) * 1000)
        logger.warning("%s (sin guardar: base cerca de la cuota)", result)
        return result

    sources_by_id = {s.id: s for s in sources}
    run = IngestRunResult(source_slug="live")
    for source_id, items in fetched:
        source = sources_by_id[source_id]
        for item in items:
            try:
                _upsert_listing(db, source, item, run)
                db.commit()
            except (SQLAlchemyError, ValueError) as exc:
                db.rollback()
                logger.warning("live[%s]: no se pudo guardar un item: %s", source.slug, exc)

    result.inserted = run.inserted
    result.updated = run.updated

    # Sin esto las publicaciones nuevas quedan con `product_id = NULL` y no aparecen en
    # `/search`, que hace INNER JOIN contra `product`.
    if run.inserted:
        try:
            match_listings(db)
        except SQLAlchemyError as exc:
            db.rollback()
            logger.warning("live[%r]: el matching falló: %s", clean, exc)

    result.elapsed_ms = int((time.monotonic() - started) * 1000)
    logger.info("%s", result)
    return result

"""Corrida diaria: refresca los precios de todas las fuentes activas y limpia el cache.

Es el trabajo que convierte a Cotejo de "una foto del dia que corriste la ingesta" en un
comparador con historial. Sin esto, `price_history` tiene un punto por publicacion y la
promesa de detectar ofertas que en realidad no bajaron nada no se puede cumplir: no hay
contra que comparar.

    python -m app.workers.daily                # refresca todo y hace mantenimiento
    python -m app.workers.daily --dry-run      # dice que haria, sin tocar nada
    python -m app.workers.daily --only fravega cetrogar
    python -m app.workers.daily --skip-maintenance

Pensado para un programador de tareas: cron en el servidor, tarea programada de Windows
en local, o un cron job del hosting. No requiere Redis ni Celery — cuando haga falta
paralelizar, este mismo modulo es lo que la tarea de Celery va a llamar.

Decisiones que importan:

- **Modo refresh, no busqueda.** Se releen los `external_id` que ya estan en la base en
  vez de buscar terminos nuevos. Es lo que alimenta `price_history` y detecta bajas; y no
  hace crecer la base, que es justo lo que el plan gratis no aguanta. El catalogo crece
  por otro lado: la busqueda en vivo agrega lo que la gente realmente busca.

- **Una fuente que falla no corta la corrida.** Si Fravega esta caida, las otras ocho
  tienen que actualizarse igual. Cada fuente va en su propio `try` y su error se reporta
  al final.

- **El matcher corre una sola vez, al final.** Es O(n^2) sobre las publicaciones nuevas;
  correrlo por fuente seria pagarlo nueve veces por la misma corrida.

- **El mantenimiento va despues de refrescar**, no antes: primero se escribe el historial
  del dia, y recien despues se aplica la retencion de 90 dias y la eviccion si la base
  esta cerca de la cuota.
"""

from __future__ import annotations

import argparse
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.errors import UnsupportedFetchMode
from app.adapters.types import RefreshRequest
from app.enums import SourceStatus
from app.models.listing import Listing
from app.models.retailer_source import RetailerSource
from app.workers.ingest import run_ingest

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class SourceOutcome:
    """Como le fue a una fuente en la corrida."""

    slug: str
    refreshed: int = 0
    price_points: int = 0
    #: Publicaciones que se pidieron y la tienda ya no devolvio: descatalogadas.
    delisted: int = 0
    skipped_reason: str | None = None
    error: str | None = None

    @property
    def status(self) -> str:
        if self.error:
            return "ERROR"
        if self.skipped_reason:
            return "OMITIDA"
        return "OK"


@dataclass
class DailyReport:
    outcomes: list[SourceOutcome] = field(default_factory=list)
    matched: str | None = None
    maintenance: str | None = None
    seconds: float = 0.0

    def render(self) -> str:
        lineas = [f"corrida diaria — {len(self.outcomes)} fuentes, {self.seconds:.1f}s"]
        for o in self.outcomes:
            detalle = o.error or o.skipped_reason or (
                f"{o.refreshed} publicaciones, {o.price_points} puntos de historial"
                + (f", {o.delisted} descatalogadas" if o.delisted else "")
            )
            lineas.append(f"  [{o.status:7}] {o.slug:14} {detalle}")
        if self.matched is not None:
            lineas.append(f"  matcher: {self.matched}")
        if self.maintenance:
            lineas.append(f"  mantenimiento: {self.maintenance}")
        return "\n".join(lineas)

    @property
    def failed(self) -> list[str]:
        return [o.slug for o in self.outcomes if o.error]


def _active_sources(db: Session, only: list[str] | None) -> list[RetailerSource]:
    stmt = select(RetailerSource).where(RetailerSource.status == SourceStatus.ACTIVE)
    if only:
        stmt = stmt.where(RetailerSource.slug.in_(only))
    return list(db.scalars(stmt.order_by(RetailerSource.slug)).all())


def _external_ids(db: Session, source: RetailerSource) -> list[str]:
    return list(
        db.scalars(
            select(Listing.external_id).where(Listing.retailer_source_id == source.id)
        ).all()
    )


class FuenteDesconocida(LookupError):
    """`--only` con un slug que no existe o no esta activo.

    Sin esto, un typo (`--only fravgea`) devolvia un reporte vacio y codigo de salida 0:
    exactamente igual que una corrida exitosa.
    """


def _marcar_descatalogadas(
    db: Session, source: RetailerSource, pedidos: list[str], desde: datetime
) -> int:
    """Marca como no disponibles las publicaciones que la tienda dejo de devolver.

    Cuando un retailer deja de vender algo, su API simplemente no lo trae mas. Sin esto,
    la publicacion se queda en la base con el ultimo precio que se le conocio, para
    siempre — y como el sitio ordena de mas barato a mas caro, un precio viejo tiende a
    quedar primero. Se vio con un Smart TV de Fravega a $109.999 que ya no existia,
    apareciendo como la mejor oferta contra el mismo modelo a $629.999 en Naldo.

    No se borran: se conserva el historial de precios, y si la tienda vuelve a
    publicarlas el proximo refresh limpia la marca sola.
    """
    if not pedidos:
        return 0

    # `desde` se toma ANTES de refrescar. El upsert pisa `fetched_at` en cada publicacion
    # que si volvio, asi que las que quedaron con una marca anterior a `desde` son
    # exactamente las que la tienda ya no devuelve.
    faltantes = (
        db.query(Listing)
        .filter(
            Listing.retailer_source_id == source.id,
            Listing.external_id.in_(pedidos),
            Listing.fetched_at < desde,
            Listing.unavailable_since.is_(None),
        )
        .all()
    )
    ahora = _utcnow()
    for listing in faltantes:
        listing.unavailable_since = ahora
    if faltantes:
        db.commit()
    return len(faltantes)


def run_daily(
    db: Session,
    *,
    only: list[str] | None = None,
    dry_run: bool = False,
    skip_maintenance: bool = False,
) -> DailyReport:
    inicio = time.monotonic()
    report = DailyReport()

    fuentes = _active_sources(db, only)
    if only:
        faltantes = sorted(set(only) - {s.slug for s in fuentes})
        if faltantes:
            raise FuenteDesconocida(
                f"no existen o no estan activas: {', '.join(faltantes)}"
            )

    for source in fuentes:
        outcome = SourceOutcome(slug=source.slug)
        report.outcomes.append(outcome)

        external_ids = _external_ids(db, source)
        if not external_ids:
            # Normal en una fuente recien agregada: todavia no la busco nadie. La
            # busqueda en vivo la va a poblar sola en cuanto alguien busque algo suyo.
            outcome.skipped_reason = "sin publicaciones que refrescar"
            continue

        if dry_run:
            outcome.skipped_reason = f"dry-run: refrescaria {len(external_ids)} publicaciones"
            continue

        try:
            # `run_ingest` no corre el matcher (eso lo hace el CLI de `ingest`), que
            # es justo lo que queremos: acá se corre una sola vez al final.
            # Antes de refrescar, para poder distinguir despues cuales no volvieron.
            antes = _utcnow()
            resultado = run_ingest(db, source, RefreshRequest(external_ids=external_ids))
            outcome.refreshed = resultado.updated + resultado.inserted
            outcome.price_points = resultado.price_points_added
            outcome.delisted = _marcar_descatalogadas(db, source, external_ids, antes)
        except UnsupportedFetchMode:
            # No es una falla: es una fuente cuyo buscador no permite pedir por id
            # (Megatone/Doofinder). Marcarlo como ERROR haría que la tarea programada
            # reporte fallo TODOS los días, y un error que suena siempre no se escucha.
            db.rollback()
            outcome.skipped_reason = "la fuente no permite releer publicaciones por id"
        except Exception as exc:
            # Una fuente caida no puede dejar sin actualizar a las otras ocho.
            db.rollback()
            outcome.error = f"{type(exc).__name__}: {exc}"
            logger.warning("fuente %s fallo: %s", source.slug, exc)

    if not dry_run:
        # El matcher y el mantenimiento van en su propio try: si revientan, el resumen
        # de lo que SÍ se refrescó tiene que llegar igual al log. Sin esto, una excepción
        # acá se lleva puesto el reporte entero de una corrida de dos minutos.
        from app.matching.matcher import match_listings

        try:
            report.matched = str(match_listings(db))
        except Exception as exc:
            db.rollback()
            report.matched = f"FALLO: {type(exc).__name__}: {exc}"
            logger.warning("el matcher fallo: %s", exc)

        if not skip_maintenance:
            from app.services.maintenance import run_maintenance

            try:
                report.maintenance = str(run_maintenance(db))
            except Exception as exc:
                db.rollback()
                report.maintenance = f"FALLO: {type(exc).__name__}: {exc}"
                logger.warning("el mantenimiento fallo: %s", exc)

    report.seconds = time.monotonic() - inicio
    return report


def main(argv: list[str] | None = None) -> int:
    from app.db import SessionLocal

    parser = argparse.ArgumentParser(
        prog="python -m app.workers.daily",
        description="Refresca los precios de todas las fuentes activas y limpia el cache.",
    )
    parser.add_argument(
        "--only", nargs="+", default=None, metavar="SLUG", help="Solo estas fuentes."
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Decir que haria, sin tocar nada."
    )
    parser.add_argument(
        "--skip-maintenance",
        action="store_true",
        help="No correr la retencion ni la eviccion al terminar.",
    )
    parser.add_argument(
        "--log-file",
        default=None,
        metavar="RUTA",
        help=(
            "Escribir el log y el resumen a un archivo en vez de la consola. Es lo que "
            "usa la tarea programada: se ejecuta con pythonw.exe, que no abre ventana y "
            "por lo tanto no tiene consola donde escribir."
        ),
    )
    args = parser.parse_args(argv)

    formato = "%(asctime)s %(levelname)s %(message)s"
    if args.log_file:
        ruta = Path(args.log_file)
        ruta.parent.mkdir(parents=True, exist_ok=True)
        logging.basicConfig(
            level=logging.INFO, format=formato, filename=str(ruta), encoding="utf-8"
        )
    else:
        logging.basicConfig(level=logging.INFO, format=formato)
    # httpx loguea una línea por request y el refresh de Frávega son cientos: el
    # resumen del final se perdía entre 267 "HTTP/1.1 200 OK".
    logging.getLogger("httpx").setLevel(logging.WARNING)

    with SessionLocal() as db:
        try:
            report = run_daily(
                db,
                only=args.only,
                dry_run=args.dry_run,
                skip_maintenance=args.skip_maintenance,
            )
        except FuenteDesconocida as exc:
            parser.error(str(exc))
            return 2  # inalcanzable: `parser.error` termina el proceso.
        if args.log_file:
            # Sin consola, el resumen tiene que ir al log o se pierde.
            logger.info(chr(10) + report.render())
        else:
            print(report.render())

    # Exit code 1 si alguna fuente fallo: un cron que no revisa la salida igual deja
    # rastro en su propio log de errores.
    return 1 if report.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

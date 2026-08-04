"""Mantenimiento del caché: retención del historial + evicción de lo frío.

Pensado para correr una vez por día (cron / tarea programada / Celery beat).

    python -m app.workers.maintenance              # retención siempre, evicción si hace falta
    python -m app.workers.maintenance --status     # solo informar, no tocar nada
    python -m app.workers.maintenance --evict      # forzar evicción aunque haya lugar
    python -m app.workers.maintenance --evict --limit 2000
"""

from __future__ import annotations

import argparse
import logging

from app.db import SessionLocal
from app.services.maintenance import run_maintenance, storage_status


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m app.workers.maintenance")
    parser.add_argument(
        "--status", action="store_true", help="Solo mostrar el uso de espacio."
    )
    parser.add_argument(
        "--evict",
        action="store_true",
        help="Forzar la evicción aunque la base no haya llegado al umbral.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=500,
        help="Máximo de productos a borrar en esta corrida (default: 500).",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    with SessionLocal() as db:
        if args.status:
            print(storage_status(db))
            return 0
        report = run_maintenance(db, force_evict=args.evict, evict_limit=args.limit)
        print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

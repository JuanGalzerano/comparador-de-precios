"""Corre el matcher sobre las publicaciones de la base.

    python -m app.workers.match             # solo las que no tienen producto
    python -m app.workers.match --all       # re-evalúa todas (tras cambiar el umbral)
"""

from __future__ import annotations

import argparse
import logging

from app.db import SessionLocal
from app.matching.matcher import match_listings


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m app.workers.match")
    parser.add_argument(
        "--all",
        action="store_true",
        help="Re-evalúa todas las publicaciones, no solo las que no tienen producto.",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    with SessionLocal() as db:
        stats = match_listings(db, only_unmatched=not args.all)
    print(stats)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

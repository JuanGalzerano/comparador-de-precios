"""Siembra `retailer_source` contra la base que diga `DATABASE_URL`.

Es el paso que falta entre `alembic upgrade head` y la primera ingesta: las migraciones
crean las tablas pero no insertan filas, y sin filas en `retailer_source` la ingesta
falla con `SourceNotConfigured` y `/sources` devuelve vacío.

    python -m scripts.seed_sources            # crea lo que falte, no pisa nada
    python -m scripts.seed_sources --update   # ademas actualiza config/nombre de las que ya existen

Idempotente: correrlo dos veces no duplica ni rompe. NUNCA borra datos — a diferencia de
`seed_dev_db.py`, que es solo para desarrollo local y arranca borrando `dev.db`.
"""

from __future__ import annotations

import argparse
import sys

from sqlalchemy import select

from app.config import settings
from app.db import SessionLocal
from app.enums import SourceKind, SourceStatus
from app.models.retailer_source import RetailerSource

#: Las fuentes que el código sabe atender hoy. El `slug` es la clave que resuelve el
#: adapter (`app/adapters/registry.py`), así que no se cambia sin tocar el registry.
SOURCES: list[dict] = [
    {
        "slug": "fravega",
        "display_name": "Frávega",
        "kind": SourceKind.VTEX,
        "status": SourceStatus.ACTIVE,
        "config_json": {"base_url": "https://www.fravega.com"},
        "tos_risk_note": None,
    },
    {
        "slug": "cetrogar",
        "display_name": "Cetrogar",
        "kind": SourceKind.VTEX,
        "status": SourceStatus.ACTIVE,
        "config_json": {"base_url": "https://www.cetrogar.com.ar"},
        "tos_risk_note": None,
    },
    {
        "slug": "naldo",
        "display_name": "Naldo",
        "kind": SourceKind.VTEX,
        "status": SourceStatus.ACTIVE,
        "config_json": {"base_url": "https://www.naldo.com.ar"},
        "tos_risk_note": None,
    },
    {
        "slug": "oncity",
        "display_name": "OnCity",
        "kind": SourceKind.VTEX,
        "status": SourceStatus.ACTIVE,
        # VTEX clásico: devuelve 404 en Intelligent Search (ver `VtexAdapter`).
        "config_json": {
            "base_url": "https://www.oncity.com",
            "api_flavor": "legacy_catalog",
        },
        "tos_risk_note": None,
    },
    {
        "slug": "megatone",
        "display_name": "Megatone",
        "kind": SourceKind.SCRAPER,
        "status": SourceStatus.ACTIVE,
        # Doofinder: el `hashid` sale del script de configuración del sitio, ver
        # `app/adapters/doofinder.py`.
        "config_json": {
            "base_url": "https://www.megatone.net",
            "hashid": "7d78864dfd68192d967ce98f7af00970",
            "zone": "us1",
        },
        "tos_risk_note": None,
    },
    {
        "slug": "compragamer",
        "display_name": "Compra Gamer",
        "kind": SourceKind.SCRAPER,
        "status": SourceStatus.ACTIVE,
        "config_json": {
            "base_url": "https://compragamer.com",
            "static_url": "https://static.compragamer.com",
        },
        "tos_risk_note": None,
    },
    {
        "slug": "mercadolibre",
        "display_name": "MercadoLibre",
        "kind": SourceKind.API,
        # Arranca inactiva a proposito: sin `ML_ACCESS_TOKEN` la API devuelve 403 en
        # todos los endpoints. Se activa sola en la primera ingesta exitosa.
        "status": SourceStatus.BLOCKED_TOS_REVIEW,
        "config_json": {"site_id": "MLA"},
        "tos_risk_note": (
            "La API pública pasó a requerir OAuth: hace falta registrar una app en el "
            "portal de desarrolladores para reactivarla (ver PENDIENTE.md)."
        ),
    },
]


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m scripts.seed_sources")
    parser.add_argument(
        "--update",
        action="store_true",
        help="Actualiza display_name/config_json/tos_risk_note de las fuentes existentes.",
    )
    args = parser.parse_args()

    print(f"base: {settings.database_url.split('@')[-1]}")

    created, updated, skipped = 0, 0, 0
    with SessionLocal() as db:
        for spec in SOURCES:
            existing = db.scalar(
                select(RetailerSource).where(RetailerSource.slug == spec["slug"])
            )
            if existing is None:
                db.add(RetailerSource(**spec))
                created += 1
                print(f"  + {spec['slug']}")
                continue

            if args.update:
                existing.display_name = spec["display_name"]
                existing.config_json = spec["config_json"]
                existing.tos_risk_note = spec["tos_risk_note"]
                # `status` NO se pisa: lo maneja el worker segun le vaya a la ingesta.
                updated += 1
                print(f"  ~ {spec['slug']}")
            else:
                skipped += 1
                print(f"  = {spec['slug']} (ya existe)")
        db.commit()

    print(f"creadas={created} actualizadas={updated} sin_cambios={skipped}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

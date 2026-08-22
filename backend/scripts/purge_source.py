"""Borra las publicaciones de una fuente, para volver a cargarla desde cero.

    python -m scripts.purge_source carrefour easy
    python -m scripts.purge_source carrefour --dry-run

Existe porque cambiar la configuración de una fuente **no** toca lo que ya se guardó.
Cuando a Carrefour y a Easy se les puso el filtro de categoría de electro, las góndolas de
almacén que habían entrado antes siguieron en la base — y la home del sitio mostraba papel
higiénico en un comparador de electrodomésticos.

No borra la fuente ni su historial de configuración: solo sus publicaciones, para que la
próxima ingesta las traiga con las reglas nuevas. Los productos que quedan sin ninguna
publicación los limpia el mantenimiento.
"""

from __future__ import annotations

import argparse

from sqlalchemy import delete, func, select

from app.db import SessionLocal
from app.models.listing import Listing
from app.models.retailer_source import RetailerSource


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m scripts.purge_source")
    parser.add_argument("slugs", nargs="+", help="Fuentes a vaciar, por slug.")
    parser.add_argument(
        "--dry-run", action="store_true", help="Decir cuántas borraría, sin borrar."
    )
    args = parser.parse_args()

    with SessionLocal() as db:
        fuentes = {
            s.slug: s
            for s in db.scalars(
                select(RetailerSource).where(RetailerSource.slug.in_(args.slugs))
            ).all()
        }
        faltantes = sorted(set(args.slugs) - set(fuentes))
        if faltantes:
            parser.error(f"no existen: {', '.join(faltantes)}")

        total = 0
        for slug in args.slugs:
            source = fuentes[slug]
            n = db.execute(
                select(func.count())
                .select_from(Listing)
                .where(Listing.retailer_source_id == source.id)
            ).scalar_one()
            total += n
            if args.dry_run:
                print(f"  {slug:14} borraría {n} publicaciones")
                continue
            db.execute(delete(Listing).where(Listing.retailer_source_id == source.id))
            print(f"  {slug:14} {n} publicaciones borradas")

        if not args.dry_run:
            db.commit()
            print(f"\ntotal: {total}. Volvé a correr la ingesta para repoblarlas.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

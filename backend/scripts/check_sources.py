"""Chequeo en vivo de cada fuente: ¿contesta desde ACÁ?

    python -m scripts.check_sources
    python -m scripts.check_sources --term heladera

Existe porque una fuente puede andar perfecto desde una máquina y estar bloqueada desde
otra. Los retailers filtran por reputación de IP: las de datacenter (Railway, Render, AWS)
levantan sospecha donde una IP residencial pasa sin problema. Verificado el 2026-08-20:
Frávega responde 200 desde una conexión hogareña argentina y 403 desde un contenedor de
Railway en EU West.

Correrlo **dentro del contenedor de producción** es la única forma de saber qué fuentes
sirven realmente ahí. Que ande en tu notebook no dice nada.
"""

from __future__ import annotations

import argparse
import logging

from sqlalchemy import select

from app.adapters.registry import build_adapter
from app.adapters.types import SearchQuery
from app.db import SessionLocal
from app.models.retailer_source import RetailerSource


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m scripts.check_sources")
    parser.add_argument("--term", default="smart tv", help="Qué buscar (default: 'smart tv').")
    parser.add_argument("--max", type=int, default=3, dest="maximo")
    args = parser.parse_args()

    logging.disable(logging.INFO)

    fallaron: list[str] = []
    with SessionLocal() as db:
        fuentes = db.scalars(select(RetailerSource).order_by(RetailerSource.slug)).all()

        print(f"buscando {args.term!r} en {len(fuentes)} fuentes\n")
        print(f"{'fuente':14} {'estado':22} resultado")
        print("-" * 74)

        for source in fuentes:
            try:
                adapter = build_adapter(source)
                crudos = list(
                    adapter.fetch_listings(SearchQuery(term=args.term, max_results=args.maximo))
                )
                normalizadas = 0
                precio = None
                for raw in crudos:
                    try:
                        listing = adapter.normalize(raw)
                        normalizadas += 1
                        precio = precio or listing.price
                    except Exception:
                        pass
                if normalizadas:
                    detalle = f"OK   {normalizadas}/{len(crudos)} normalizadas, ${precio}"
                else:
                    detalle = f"VACIO  {len(crudos)} crudas, 0 normalizadas"
                    fallaron.append(source.slug)
            except Exception as exc:
                detalle = f"FALLA  {type(exc).__name__}: {str(exc)[:38]}"
                fallaron.append(source.slug)

            print(f"{source.slug:14} {source.status.value:22} {detalle}")

    if fallaron:
        print(f"\nsin resultados: {', '.join(fallaron)}")
    # Código 1 si alguna falló, para que un chequeo automatizado lo note.
    return 1 if fallaron else 0


if __name__ == "__main__":
    raise SystemExit(main())

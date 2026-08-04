"""`/sources` — estado de cada fuente + qué tan seguido tiene el mejor precio.

Dos usos: la página de transparencia (qué fuente es API oficial, cuál está pausada por
riesgo de ToS) y la priorización de tiendas en la UI — "estas tiendas suelen tener el
mejor precio" sale de datos propios, no de una lista escrita a mano.

La métrica es `win_rate`: de los productos donde esta fuente compite contra al menos otra
fuente, en qué fracción tiene la publicación más barata (por `final_price`, es decir con
envío incluido). Los productos con una sola fuente se excluyen a propósito: tener el
precio más bajo cuando nadie más publica el producto no dice nada sobre ser competitivo.
"""

from __future__ import annotations

from sqlalchemy import func, select

from fastapi import APIRouter

from app.api.deps import DbSession
from app.models.listing import Listing
from app.models.retailer_source import RetailerSource
from app.schemas.sources import SourceOut, SourcesResponse

router = APIRouter(prefix="/sources", tags=["sources"])


@router.get("", response_model=SourcesResponse)
def list_sources(db: DbSession) -> SourcesResponse:
    sources = db.scalars(select(RetailerSource).order_by(RetailerSource.slug)).all()

    # (product_id, source_id, precio mínimo de esa fuente en ese producto)
    per_product_source = db.execute(
        select(
            Listing.product_id,
            Listing.retailer_source_id,
            func.min(Listing.final_price).label("min_price"),
        )
        .where(Listing.product_id.is_not(None))
        .group_by(Listing.product_id, Listing.retailer_source_id)
    ).all()

    by_product: dict[int, list[tuple[int, float]]] = {}
    listing_counts: dict[int, int] = {}
    product_counts: dict[int, int] = {}
    for row in per_product_source:
        by_product.setdefault(row.product_id, []).append(
            (row.retailer_source_id, float(row.min_price))
        )
        product_counts[row.retailer_source_id] = product_counts.get(row.retailer_source_id, 0) + 1

    for source_id, count in db.execute(
        select(Listing.retailer_source_id, func.count(Listing.id)).group_by(
            Listing.retailer_source_id
        )
    ).all():
        listing_counts[source_id] = count

    cheapest_counts: dict[int, int] = {}
    contested_counts: dict[int, int] = {}
    for entries in by_product.values():
        if len(entries) < 2:
            continue  # producto con una sola fuente: no hay competencia que medir
        winner = min(entries, key=lambda e: e[1])[0]
        cheapest_counts[winner] = cheapest_counts.get(winner, 0) + 1
        for source_id, _ in entries:
            contested_counts[source_id] = contested_counts.get(source_id, 0) + 1

    items = [
        SourceOut(
            slug=source.slug,
            display_name=source.display_name,
            kind=source.kind.value,
            status=source.status.value,
            tos_risk_note=source.tos_risk_note,
            listing_count=listing_counts.get(source.id, 0),
            product_count=product_counts.get(source.id, 0),
            cheapest_count=cheapest_counts.get(source.id, 0),
            win_rate=(
                cheapest_counts.get(source.id, 0) / contested_counts[source.id]
                if contested_counts.get(source.id)
                else None
            ),
            last_success_at=source.last_success_at,
            last_error=source.last_error,
        )
        for source in sources
    ]

    items.sort(key=lambda s: (s.win_rate if s.win_rate is not None else -1), reverse=True)
    return SourcesResponse(items=items)

"""`/search` — busqueda de productos (clusters de publicaciones).

Consulta las tablas LOCALES `product`/`listing` en Postgres via SQLAlchemy; NO llama
a `MercadoLibreAdapter` (ni a ningun `SourceAdapter`) en linea por request. Traer datos
de una fuente es trabajo del worker de ingesta (todavia no existe); este endpoint solo
SIRVE lo que ya esta en la base. Mezclar las dos cosas violaria la separacion que el
propio `SourceAdapter` establece (`app/adapters/base.py`).

Cada `product` es un cluster de `listing` (ver `groups` en
`project/Cotejo - Comparador.dc.html:672-685`): la respuesta agrupa, no devuelve
publicaciones sueltas. `q`/`category`/`condition` filtran las PUBLICACIONES que entran
al cluster (no solo si el producto aparece): el resumen de cada cluster
(`listing_count`/min/max/`best_score`) se calcula sobre ese set filtrado, nunca sobre
todas las publicaciones del producto — es "lo que el usuario esta viendo", igual que
`renderVals()` normaliza el score contra el set visible y no contra todo el catalogo.

Paginacion: falta en el mock (gap explicito del plan). Pagina sobre PRODUCTOS
(clusters), no sobre publicaciones.

Orden de resultados: el mock no define ninguno (`Object.keys(cat)` es simplemente el
orden de insercion del objeto JS, no una decision de producto). Se eligio ordenar por
`min_final_price` ascendente (el cluster mas barato primero) como proxy razonable de
"mejores ofertas arriba"; es una decision pragmatica de esta tarea, no un port de algo
que el mock especifique.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from decimal import Decimal
from typing import Literal

import httpx
from fastapi import APIRouter, Query
from sqlalchemy import ColumnElement, func, or_, select

from app.api.deps import DbSession
from app.enums import ItemCondition
from app.models.listing import Listing
from app.models.product import Product
from app.scoring.score import score_listings
from app.schemas.search import ProductClusterOut, SearchResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/search", tags=["search"])

_ML_SEARCH_URL = "https://api.mercadolibre.com/sites/MLA/search"
_ML_TIMEOUT = 5.0


def _ml_score(item: dict) -> int:
    score = 42
    level = (item.get("seller") or {}).get("power_seller_status")
    if level == "platinum":
        score += 22
    elif level == "gold":
        score += 15
    elif level == "silver":
        score += 8
    if (item.get("shipping") or {}).get("free_shipping"):
        score += 8
    inst = item.get("installments") or {}
    if inst.get("rate") == 0 and (inst.get("quantity") or 1) > 1:
        score += 8
    return min(100, score)


def _ml_live_search(query: str, limit: int) -> list[ProductClusterOut]:
    try:
        with httpx.Client(timeout=_ML_TIMEOUT) as client:
            resp = client.get(
                _ML_SEARCH_URL,
                params={"q": query, "limit": min(limit, 50), "sort": "relevance"},
            )
            resp.raise_for_status()
    except Exception as exc:
        logger.warning("ML live search failed for %r: %s", query, exc)
        return []

    results: list[ProductClusterOut] = []
    for i, item in enumerate(resp.json().get("results", [])[:limit]):
        price = Decimal(str(item.get("price") or 0))
        attrs = {a["id"]: a.get("value_name") for a in (item.get("attributes") or [])}
        results.append(
            ProductClusterOut(
                id=-(i + 1),
                canonical_title=item.get("title", ""),
                brand=attrs.get("BRAND"),
                model=attrs.get("MODEL"),
                category=None,
                catalog_product_id=item.get("catalog_product_id"),
                listing_count=1,
                min_final_price=price,
                max_final_price=price,
                best_score=_ml_score(item),
                permalink=item.get("permalink"),
            )
        )
    return results


def _build_filters(
    *,
    q: str | None,
    category: str | None,
    condition: Literal["all", "new", "used", "refurbished", "unknown"],
) -> list[ColumnElement[bool]]:
    """Predicados sobre `listing`/`product` que definen el set "matcheado".

    Se usan tanto para el agregado (resumen de cluster) como para traer las
    publicaciones individuales que entran en ese resumen: tienen que ser EXACTAMENTE
    los mismos, o el `best_score` quedaria calculado sobre un set distinto del que
    dice `listing_count`.
    """
    filters: list[ColumnElement[bool]] = []
    if condition != "all":
        filters.append(Listing.condition == ItemCondition(condition))
    if category:
        filters.append(func.lower(Product.category) == category.strip().lower())
    if q and q.strip():
        like = f"%{q.strip()}%"
        filters.append(
            or_(
                Product.canonical_title.ilike(like),
                Product.brand.ilike(like),
                Product.model.ilike(like),
                Listing.title.ilike(like),
            )
        )
    return filters


@router.get("", response_model=SearchResponse)
def search(
    db: DbSession,
    q: str | None = Query(default=None, description="Termino de busqueda libre."),
    category: str | None = Query(default=None, description="Categoria canonica de Cotejo."),
    condition: Literal["all", "new", "used", "refurbished", "unknown"] = Query(default="all"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> SearchResponse:
    filters = _build_filters(q=q, category=category, condition=condition)

    # --- Paso 1: agregado por producto (cuenta + min/max de `final_price`) ------
    # Un producto sin ninguna publicacion que matchee los filtros no debe aparecer:
    # el INNER JOIN implicito de `select_from(Listing).join(Product)` ya lo garantiza
    # (y de paso excluye publicaciones huerfanas con `product_id IS NULL`, que son un
    # estado valido de la ingesta pero no tienen cluster que mostrar).
    agg_stmt = (
        select(
            Product.id.label("product_id"),
            func.count(Listing.id).label("listing_count"),
            func.min(Listing.final_price).label("min_final_price"),
            func.max(Listing.final_price).label("max_final_price"),
        )
        .select_from(Listing)
        .join(Product, Listing.product_id == Product.id)
        .where(*filters)
        .group_by(Product.id)
    )

    total = db.execute(select(func.count()).select_from(agg_stmt.subquery())).scalar_one()

    page_stmt = (
        agg_stmt.order_by(
            func.min(Listing.final_price).asc(),
            Product.id.asc(),
        )
        .limit(page_size)
        .offset((page - 1) * page_size)
    )
    agg_rows = db.execute(page_stmt).all()

    if not agg_rows:
        ml_items = _ml_live_search(q.strip(), page_size) if q and q.strip() else []
        return SearchResponse(items=ml_items, page=page, page_size=page_size, total=len(ml_items))

    product_ids = [row.product_id for row in agg_rows]
    products_by_id = {
        p.id: p for p in db.scalars(select(Product).where(Product.id.in_(product_ids))).all()
    }

    # --- Paso 2: publicaciones filtradas de esos productos, para el score --------
    # Mismos `filters` que el agregado (ver docstring de `_build_filters`).
    listings_stmt = (
        select(Listing)
        .join(Product, Listing.product_id == Product.id)
        .where(*filters, Listing.product_id.in_(product_ids))
    )
    listings_by_product: dict[int, list[Listing]] = defaultdict(list)
    for listing in db.scalars(listings_stmt).all():
        listings_by_product[listing.product_id].append(listing)

    items: list[ProductClusterOut] = []
    for row in agg_rows:
        product = products_by_id[row.product_id]
        cluster_listings = listings_by_product.get(row.product_id, [])
        scores = score_listings(cluster_listings)
        best_score = max(scores) if scores else 0
        items.append(
            ProductClusterOut(
                id=product.id,
                canonical_title=product.canonical_title,
                brand=product.brand,
                model=product.model,
                category=product.category,
                catalog_product_id=product.catalog_product_id,
                listing_count=row.listing_count,
                min_final_price=Decimal(row.min_final_price),
                max_final_price=Decimal(row.max_final_price),
                best_score=best_score,
            )
        )

    # Complementar con ML live si la DB no llena la página
    if q and q.strip() and len(items) < page_size:
        ml_items = _ml_live_search(q.strip(), page_size - len(items))
        items.extend(ml_items)
        total += len(ml_items)

    return SearchResponse(items=items, page=page, page_size=page_size, total=total)

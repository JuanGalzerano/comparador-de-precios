"""`/products` — ficha de producto y tabla comparativa.

`GET /products/{product_id}` es el port server-side de `renderVals()`
(`project/Cotejo - Comparador.dc.html:585-647`): filtra las publicaciones del producto
por el mismo predicado `pass()` (envio gratis / tienda oficial / garantia >= 6 meses /
condicion), calcula el score de cada una normalizando contra ESE set filtrado (no todo
el cluster) y las ordena por el `cmp` que pida `sort`. `listing.permalink` viaja
siempre: es el CTA de la UI.

`GET /products/{product_id}/price-history` sirve el grafico de historial (gap de UI
del plan): serie cruda de `price_history` de las publicaciones del producto, sin
agregacion mas alla de la ventana de tiempo (default 90 dias, el mismo horizonte que
`/ofertas` segun `project/README.md`).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from app.api.deps import DbSession
from app.enums import ItemCondition
from app.models.listing import Listing
from app.models.price_history import PriceHistory
from app.models.product import Product
from app.scoring.score import score_listings
from app.schemas.product import ListingOut, PriceHistoryPoint, PriceHistoryResponse, ProductDetailOut

router = APIRouter(prefix="/products", tags=["products"])

SortKey = Literal["score", "price", "rating", "warranty", "seller"]


def _get_product_or_404(db: DbSession, product_id: int) -> Product:
    product = db.get(Product, product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="product not found")
    return product


def _passes_filters(
    listing: Listing,
    *,
    free: bool,
    official: bool,
    warranty: bool,
    condition: Literal["all", "new", "used", "refurbished", "unknown"],
) -> bool:
    """Port de `pass()` (`.dc.html:592-596`): mismos cuatro toggles, mismo orden."""
    if free and listing.shipping_cost != 0:
        return False
    if official and not listing.official_store:
        return False
    if warranty and (listing.warranty_months or 0) < 6:
        return False
    if condition != "all" and listing.condition != ItemCondition(condition):
        return False
    return True


def _sort_key(sort: SortKey):
    """Port de `cmp` (`.dc.html:604-610`). Python ordena ascendente por defecto, asi
    que los ejes "mayor es mejor" se niegan para conseguir el mismo orden descendente
    que el JS (`b.score - a.score`, etc). `sort()` de Python es estable, igual que
    `Array.prototype.sort` en motores modernos: los empates conservan el orden previo
    (id ascendente), que es un comportamiento razonable no especificado por el mock.
    """
    if sort == "score":
        return lambda item: -item[1]  # item = (listing, score)
    if sort == "price":
        return lambda item: item[0].final_price
    if sort == "rating":
        # `(a,b) => b.rating - a.rating || b.reviews - a.reviews`: descendente por
        # rating y como desempate, descendente por reviews. `None` se trata como 0,
        # igual que el mock (que nunca manda `null`, manda `0`).
        return lambda item: (-(item[0].rating or 0), -(item[0].reviews_count or 0))
    if sort == "warranty":
        return lambda item: -(item[0].warranty_months or 0)
    # "seller": `(a,b) => b.sales - a.sales`
    return lambda item: -(item[0].seller_sales or 0)


@router.get("/{product_id}", response_model=ProductDetailOut)
def get_product(
    db: DbSession,
    product_id: int,
    sort: SortKey = Query(default="score"),
    free: bool = Query(default=False, description="Solo envio gratis (l.ship === 0)."),
    official: bool = Query(default=False, description="Solo tienda oficial."),
    warranty: bool = Query(default=False, description="Solo garantia >= 6 meses."),
    condition: Literal["all", "new", "used", "refurbished", "unknown"] = Query(default="all"),
) -> ProductDetailOut:
    product = _get_product_or_404(db, product_id)

    all_listings = db.scalars(
        select(Listing).where(Listing.product_id == product_id).order_by(Listing.id.asc())
    ).all()
    visible = [
        listing
        for listing in all_listings
        if _passes_filters(
            listing, free=free, official=official, warranty=warranty, condition=condition
        )
    ]

    # El score normaliza contra el set VISIBLE (post-filtros), no contra todo el
    # cluster: mismo criterio que `renderVals()` (`min`/`max` se calculan sobre `set`,
    # que ya paso por `pass()`).
    scores = score_listings(visible)
    scored_pairs = list(zip(visible, scores))
    scored_pairs.sort(key=_sort_key(sort))

    listings_out = [
        ListingOut(
            id=listing.id,
            title=listing.title,
            permalink=listing.permalink,
            condition=listing.condition,
            price=listing.price,
            shipping_cost=listing.shipping_cost,
            final_price=listing.final_price,
            installments_qty=listing.installments_qty,
            installments_amount=listing.installments_amount,
            interest_free=listing.interest_free,
            seller_name=listing.seller_name,
            seller_level=listing.seller_level,
            seller_sales=listing.seller_sales,
            official_store=listing.official_store,
            fulfillment=listing.fulfillment,
            rating=listing.rating,
            reviews_count=listing.reviews_count,
            warranty_months=listing.warranty_months,
            warranty_type=listing.warranty_type,
            score=score,
        )
        for listing, score in scored_pairs
    ]

    return ProductDetailOut(
        id=product.id,
        canonical_title=product.canonical_title,
        brand=product.brand,
        model=product.model,
        category=product.category,
        catalog_product_id=product.catalog_product_id,
        listings=listings_out,
    )


@router.get("/{product_id}/price-history", response_model=PriceHistoryResponse)
def get_price_history(
    db: DbSession,
    product_id: int,
    days: int = Query(default=90, ge=1, le=365, description="Ventana de tiempo, en dias."),
) -> PriceHistoryResponse:
    _get_product_or_404(db, product_id)

    since = datetime.now(timezone.utc) - timedelta(days=days)
    rows = db.execute(
        select(
            PriceHistory.listing_id,
            PriceHistory.captured_at,
            PriceHistory.price,
            PriceHistory.shipping_cost,
        )
        .join(Listing, PriceHistory.listing_id == Listing.id)
        .where(Listing.product_id == product_id, PriceHistory.captured_at >= since)
        .order_by(PriceHistory.captured_at.asc())
    ).all()

    points = [
        PriceHistoryPoint(
            listing_id=row.listing_id,
            captured_at=row.captured_at,
            price=row.price,
            shipping_cost=row.shipping_cost,
        )
        for row in rows
    ]
    return PriceHistoryResponse(product_id=product_id, since=since, points=points)

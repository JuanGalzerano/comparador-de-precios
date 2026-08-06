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
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, select

from app.api.deps import DbSession
from app.enums import ItemCondition
from app.models.listing import Listing
from app.models.price_history import PriceHistory
from app.models.product import Product
from app.models.product_match import ProductMatch
from app.models.retailer_source import RetailerSource
from app.scoring.score import score_listings
from app.schemas.product import (
    ListingOut,
    PriceHistoryPoint,
    PriceHistoryResponse,
    ProductDetailOut,
    SimilarProductOut,
    SimilarProductsResponse,
)

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

    retailers = {
        row.id: (row.slug, row.display_name)
        for row in db.execute(
            select(RetailerSource.id, RetailerSource.slug, RetailerSource.display_name).where(
                RetailerSource.id.in_({listing.retailer_source_id for listing in visible})
            )
        ).all()
    }

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
            retailer_slug=retailers.get(listing.retailer_source_id, (None, None))[0],
            retailer_name=(
                retailers.get(listing.retailer_source_id, (None, None))[1]
                or retailers.get(listing.retailer_source_id, (None, None))[0]
            ),
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


#: Un "similar" tiene que estar en el mismo orden de precio que el producto de la ficha.
#: Fuera de esta banda es otra cosa: un accesorio (la funda del teléfono) o un producto
#: de otra gama que comparte palabras en el título.
_SIMILAR_PRICE_MIN_RATIO = 0.3
_SIMILAR_PRICE_MAX_RATIO = 3.0


def _price_is_comparable(own_price: Decimal | None, other_price: Decimal | None) -> bool:
    """`True` si los dos precios están en el mismo orden de magnitud."""
    if own_price is None or other_price is None or own_price <= 0:
        # Sin precio de referencia no se puede filtrar; se deja pasar (el usuario ve el
        # precio igual y decide) en vez de esconder resultados por falta de dato.
        return True
    ratio = float(other_price) / float(own_price)
    return _SIMILAR_PRICE_MIN_RATIO <= ratio <= _SIMILAR_PRICE_MAX_RATIO


@router.get("/{product_id}/similar", response_model=SimilarProductsResponse)
def get_similar(
    db: DbSession,
    product_id: int,
    limit: int = Query(default=6, ge=1, le=20),
) -> SimilarProductsResponse:
    """Productos PARECIDOS al de la ficha, con su precio.

    No son el mismo producto: son los candidatos que el matcher evaluó y no aplicó (ver
    `SimilarProductOut`). Se separan del cluster a propósito — mezclarlos haría que el
    ahorro anunciado compare cosas distintas — pero se muestran aparte porque un modelo
    vecino más barato es información útil para decidir.

    La relación es simétrica: sirve tanto un candidato que salió de una publicación de
    ESTE producto, como uno de otro producto que apuntaba a este.
    """
    _get_product_or_404(db, product_id)

    mine = (
        select(ProductMatch.product_id.label("other_id"), ProductMatch.confidence)
        .join(Listing, Listing.id == ProductMatch.listing_id)
        .where(Listing.product_id == product_id, ProductMatch.product_id != product_id)
    )
    theirs = (
        select(Listing.product_id.label("other_id"), ProductMatch.confidence)
        .join(Listing, Listing.id == ProductMatch.listing_id)
        .where(
            ProductMatch.product_id == product_id,
            Listing.product_id.is_not(None),
            Listing.product_id != product_id,
        )
    )

    # Un mismo par puede aparecer por los dos lados: se queda la confianza más alta.
    best: dict[int, float] = {}
    for other_id, confidence in db.execute(mine.union_all(theirs)).all():
        if other_id is None:
            continue
        best[other_id] = max(best.get(other_id, 0.0), float(confidence))

    if not best:
        return SimilarProductsResponse(product_id=product_id, items=[])

    top_ids = [pid for pid, _ in sorted(best.items(), key=lambda kv: -kv[1])[:limit]]

    summaries = {
        row.product_id: row
        for row in db.execute(
            select(
                Listing.product_id,
                func.count(Listing.id).label("listing_count"),
                func.count(func.distinct(Listing.retailer_source_id)).label("retailer_count"),
                func.min(Listing.final_price).label("min_final_price"),
                func.max(Listing.final_price).label("max_final_price"),
            )
            .where(Listing.product_id.in_(top_ids))
            .group_by(Listing.product_id)
        ).all()
    }
    products = {p.id: p for p in db.scalars(select(Product).where(Product.id.in_(top_ids))).all()}

    # Precio del producto de la ficha, para descartar accesorios: una funda de iPhone
    # comparte casi todos los tokens del título con el teléfono, así que entra como
    # candidato — pero a $17.000 contra $1.200.000 no es una alternativa de compra.
    own_price = db.scalar(
        select(func.min(Listing.final_price)).where(Listing.product_id == product_id)
    )

    items: list[SimilarProductOut] = []
    for pid in top_ids:
        product = products.get(pid)
        summary = summaries.get(pid)
        # Un candidato puede haberse quedado sin publicaciones (evicción, o el producto
        # se fusionó): no se muestra un similar sin precio.
        if product is None or summary is None:
            continue
        if not _price_is_comparable(own_price, summary.min_final_price):
            continue
        items.append(
            SimilarProductOut(
                id=product.id,
                canonical_title=product.canonical_title,
                brand=product.brand,
                model=product.model,
                listing_count=summary.listing_count,
                retailer_count=summary.retailer_count,
                min_final_price=summary.min_final_price,
                max_final_price=summary.max_final_price,
                confidence=round(best[pid], 3),
            )
        )

    return SimilarProductsResponse(product_id=product_id, items=items)

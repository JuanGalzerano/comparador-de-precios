"""`/me/favorites` — productos guardados por el usuario logueado.

Todo el router exige sesion (`dependencies=[Depends(get_current_user)]` a nivel
`APIRouter`, no repetido endpoint por endpoint): un solo lugar gatea el prefix `/me`
entero, a diferencia de `/auth`, que es publico. Cada endpoint ademas pide `user:
CurrentUser` como parametro porque necesita el `id` del usuario, no solo el gate; FastAPI
cachea la dependencia por request, asi que esto no dispara una segunda resolucion de
sesion.

`GET /me/favorites` resume cada favorito igual que `/search` resume un cluster (conteo +
min/max de `final_price` + mejor `score_listings()`), pero sin ningun filtro `q`/
`category`/`condition`: aca el set de publicaciones de un producto es TODO lo que tiene,
no un subconjunto post-busqueda. A diferencia de `/search`, un producto guardado entra
igual aunque se haya quedado sin publicaciones vigentes (LEFT JOIN, no INNER JOIN): el
favorito no desaparece solo porque el listing se dio de baja (ver `SavedProductOut.
min_final_price`, nullable).
"""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError

from app.api.deps import CurrentUser, DbSession, get_current_user
from app.models.listing import Listing
from app.models.product import Product
from app.models.saved_product import SavedProduct
from app.scoring.score import score_listings
from app.schemas.favorites import SavedProductIdsResponse, SavedProductOut, SavedProductsResponse

router = APIRouter(prefix="/me", tags=["favorites"], dependencies=[Depends(get_current_user)])


@router.get("/favorites/ids", response_model=SavedProductIdsResponse)
def list_favorite_ids(user: CurrentUser, db: DbSession) -> SavedProductIdsResponse:
    """Solo los ids (ver docstring de `SavedProductIdsResponse`).

    Declarada ANTES que `PUT`/`DELETE /me/favorites/{product_id}` en este archivo: aunque
    el converter `int` de esos paths ya no matchearia el literal `ids`, se mantiene el
    orden por las dudas y porque es la convencion mas clara de leer.
    """
    product_ids = db.scalars(
        select(SavedProduct.product_id).where(SavedProduct.user_id == user.id)
    ).all()
    return SavedProductIdsResponse(product_ids=list(product_ids))


@router.get("/favorites", response_model=SavedProductsResponse)
def list_favorites(
    user: CurrentUser,
    db: DbSession,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> SavedProductsResponse:
    # --- Paso 1: agregado por producto guardado (cuenta + min/max de `final_price`) --
    # LEFT JOIN (no INNER, a diferencia de `/search`): un producto guardado sigue
    # apareciendo aunque no tenga ninguna publicacion vigente.
    agg_stmt = (
        select(
            SavedProduct.product_id.label("product_id"),
            SavedProduct.created_at.label("saved_at"),
            func.count(Listing.id).label("listing_count"),
            func.min(Listing.final_price).label("min_final_price"),
            func.max(Listing.final_price).label("max_final_price"),
        )
        .select_from(SavedProduct)
        .outerjoin(Listing, Listing.product_id == SavedProduct.product_id)
        .where(SavedProduct.user_id == user.id)
        .group_by(SavedProduct.product_id, SavedProduct.created_at)
    )

    total = db.execute(select(func.count()).select_from(agg_stmt.subquery())).scalar_one()

    page_stmt = (
        agg_stmt.order_by(SavedProduct.created_at.desc(), SavedProduct.product_id.desc())
        .limit(page_size)
        .offset((page - 1) * page_size)
    )
    agg_rows = db.execute(page_stmt).all()

    if not agg_rows:
        return SavedProductsResponse(items=[], page=page, page_size=page_size, total=total)

    product_ids = [row.product_id for row in agg_rows]
    products_by_id = {
        p.id: p for p in db.scalars(select(Product).where(Product.id.in_(product_ids))).all()
    }

    # --- Paso 2: TODAS las publicaciones de esos productos, para el score -----------
    # Sin filtros (no hay `q`/`category`/`condition` en favoritos): el score se calcula
    # sobre el cluster completo, igual que `/products/{id}` sin ningun toggle activado.
    listings_stmt = select(Listing).where(Listing.product_id.in_(product_ids))
    listings_by_product: dict[int, list[Listing]] = defaultdict(list)
    for listing in db.scalars(listings_stmt).all():
        listings_by_product[listing.product_id].append(listing)

    items: list[SavedProductOut] = []
    for row in agg_rows:
        product = products_by_id[row.product_id]
        cluster_listings = listings_by_product.get(row.product_id, [])
        scores = score_listings(cluster_listings)
        best_score = max(scores) if scores else 0
        items.append(
            SavedProductOut(
                id=product.id,
                canonical_title=product.canonical_title,
                brand=product.brand,
                model=product.model,
                category=product.category,
                catalog_product_id=product.catalog_product_id,
                listing_count=row.listing_count,
                min_final_price=(
                    Decimal(row.min_final_price) if row.min_final_price is not None else None
                ),
                max_final_price=(
                    Decimal(row.max_final_price) if row.max_final_price is not None else None
                ),
                best_score=best_score,
                saved_at=row.saved_at,
            )
        )

    return SavedProductsResponse(items=items, page=page, page_size=page_size, total=total)


@router.put("/favorites/{product_id}", status_code=204)
def save_favorite(product_id: int, user: CurrentUser, db: DbSession) -> None:
    """Idempotente: guardar dos veces el mismo producto no es un error, es un no-op.

    Upsert via `IntegrityError` + rollback (no `SELECT` previo + `INSERT`): asi funciona
    igual en SQLite (que no tiene `ON CONFLICT DO NOTHING` disponible de forma pareja via
    SQLAlchemy Core en todos los dialectos) y en Postgres, y no hay carrera posible entre
    el `SELECT` y el `INSERT` de dos requests concurrentes del mismo usuario.
    """
    if db.get(Product, product_id) is None:
        raise HTTPException(status_code=404, detail="product not found")

    db.add(SavedProduct(user_id=user.id, product_id=product_id))
    try:
        db.commit()
    except IntegrityError:
        # Ya estaba guardado (`uq_saved_product_user_product`): exactamente el resultado
        # que se buscaba, no hay nada mas que hacer.
        db.rollback()


@router.delete("/favorites/{product_id}", status_code=204)
def remove_favorite(product_id: int, user: CurrentUser, db: DbSession) -> None:
    """204 siempre, este o no guardado: un DELETE que no encuentra nada para borrar
    tampoco es un error."""
    db.execute(
        delete(SavedProduct).where(
            SavedProduct.user_id == user.id, SavedProduct.product_id == product_id
        )
    )
    db.commit()

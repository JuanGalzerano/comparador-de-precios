"""Asigna cada `listing` a un `product` canónico (el cluster que muestra la UI).

Dos vías, en orden de confianza:

1. **catalog_id** — si la publicación trae el id de catálogo de la fuente
   (`catalog_product_id` de ML), el producto es ese, sin ambigüedad. confidence = 1.0.
2. **fuzzy** — similitud de Jaccard sobre tokens normalizados del título, con dos
   guardas duras que evitan los falsos positivos caros de esta categoría:
   marcas distintas nunca matchean, y capacidades distintas tampoco (un iPhone 13 de
   128 GB y uno de 256 GB son productos distintos aunque el título difiera en un token).

Todo lo que se decide queda registrado en `product_match` con su método y confianza:
`listing.product_id` es el resultado aplicado, `product_match` es la evidencia auditable
que alimenta la cola de revisión.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.enums import MatchMethod
from app.matching.normalize import (
    extract_brand,
    extract_capacity_gb,
    extract_color,
    extract_model_codes,
    extract_screen_inches,
    extract_variants,
    guess_model,
    jaccard,
    normalize_text,
    tokens_for_similarity,
)
from app.models.listing import Listing
from app.models.product import Product
from app.models.product_match import ProductMatch

logger = logging.getLogger(__name__)

#: Por encima de esto la publicación se vincula sola. Los títulos reales del mismo
#: producto en distintas tiendas caen entre 0.5 y 0.7 (cada tienda ordena y abrevia
#: distinto), así que un umbral alto no matchea nada; lo que evita los falsos positivos
#: no es el umbral sino las guardas duras de `_conflicts` (marca, capacidad, variante
#: Pro/Mini/Max y código de modelo del fabricante).
AUTO_MATCH_THRESHOLD = 0.45

#: Entre este valor y el de arriba se guarda el candidato en `product_match` sin aplicarlo:
#: es la cola de revisión manual del panel admin.
REVIEW_THRESHOLD = 0.33


@dataclass(frozen=True)
class MatchStats:
    listings_seen: int = 0
    matched_by_catalog: int = 0
    matched_by_fuzzy: int = 0
    products_created: int = 0
    queued_for_review: int = 0

    def __str__(self) -> str:
        return (
            f"publicaciones={self.listings_seen} por_catalogo={self.matched_by_catalog} "
            f"por_similitud={self.matched_by_fuzzy} productos_creados={self.products_created} "
            f"a_revisar={self.queued_for_review}"
        )


@dataclass(frozen=True)
class _Fingerprint:
    """Lo que hace falta para comparar dos títulos sin volver a parsearlos."""

    tokens: frozenset[str]
    brand: str | None
    capacity_gb: int | None
    variants: frozenset[str]
    model_codes: frozenset[str]


@dataclass
class _Candidate:
    product: Product
    fingerprint: _Fingerprint


def fingerprint(title: str, *, brand: str | None = None, capacity_gb: int | None = None) -> _Fingerprint:
    return _Fingerprint(
        tokens=tokens_for_similarity(title),
        brand=brand or extract_brand(title),
        capacity_gb=capacity_gb if capacity_gb is not None else extract_capacity_gb(title),
        variants=extract_variants(title),
        model_codes=extract_model_codes(title),
    )


def _conflicts(a: _Fingerprint, b: _Fingerprint) -> bool:
    """Diferencias que descartan el match sin importar cuánto se parezcan los títulos."""
    if a.brand and b.brand and normalize_text(a.brand) != normalize_text(b.brand):
        return True
    if a.capacity_gb is not None and b.capacity_gb is not None and a.capacity_gb != b.capacity_gb:
        return True
    # "iPhone 13" vs "iPhone 13 Pro Max": mismos tokens casi todos, producto distinto.
    if a.variants != b.variants:
        return True
    # Dos códigos de fabricante distintos son dos productos distintos, punto.
    if a.model_codes and b.model_codes and not (a.model_codes & b.model_codes):
        return True
    return False


def _candidate_from_product(product: Product) -> _Candidate:
    attrs = product.attributes_json or {}
    return _Candidate(
        product=product,
        fingerprint=fingerprint(
            product.canonical_title,
            brand=product.brand,
            capacity_gb=attrs.get("capacity_gb"),
        ),
    )


def _create_product(db: Session, listing: Listing) -> Product:
    brand = extract_brand(listing.title)
    capacity = extract_capacity_gb(listing.title)
    screen = extract_screen_inches(listing.title)
    color = extract_color(listing.title)

    attributes: dict[str, object] = {}
    if capacity is not None:
        attributes["capacity_gb"] = capacity
    if screen is not None:
        attributes["screen_inches"] = screen
    if color is not None:
        attributes["color"] = color

    product = Product(
        canonical_title=listing.title[:512],
        brand=brand.upper() if brand and len(brand) <= 3 else (brand.capitalize() if brand else None),
        model=guess_model(listing.title, brand),
        category=None,
        catalog_product_id=None,
        attributes_json=attributes,
    )
    db.add(product)
    db.flush()
    return product


def _record_match(
    db: Session, listing: Listing, product: Product, method: MatchMethod, confidence: float
) -> None:
    existing = db.scalar(
        select(ProductMatch).where(
            ProductMatch.listing_id == listing.id, ProductMatch.product_id == product.id
        )
    )
    if existing:
        existing.method = method
        existing.confidence = confidence
        return
    db.add(
        ProductMatch(
            listing_id=listing.id,
            product_id=product.id,
            method=method,
            confidence=confidence,
        )
    )


def match_listings(db: Session, *, only_unmatched: bool = True) -> MatchStats:
    """Recorre las publicaciones y las agrupa en productos.

    `only_unmatched=False` re-evalúa todo (útil después de tocar el umbral o el
    normalizador); por defecto solo toca lo que todavía no tiene producto, que es lo que
    corre después de cada ingesta.
    """
    stmt = select(Listing).order_by(Listing.id)
    if only_unmatched:
        stmt = stmt.where(Listing.product_id.is_(None))
    listings = list(db.scalars(stmt))

    candidates = [
        _candidate_from_product(product) for product in db.scalars(select(Product)).all()
    ]
    by_catalog_id = {
        c.product.catalog_product_id: c for c in candidates if c.product.catalog_product_id
    }

    seen = 0
    by_catalog = 0
    by_fuzzy = 0
    created = 0
    queued = 0

    for listing in listings:
        seen += 1
        listing_fp = fingerprint(listing.title)

        catalog_id = getattr(listing, "catalog_product_id", None)
        if catalog_id and catalog_id in by_catalog_id:
            product = by_catalog_id[catalog_id].product
            listing.product_id = product.id
            _record_match(db, listing, product, MatchMethod.CATALOG_ID, 1.0)
            by_catalog += 1
            continue

        best: tuple[float, _Candidate] | None = None
        for candidate in candidates:
            if _conflicts(candidate.fingerprint, listing_fp):
                continue
            score = jaccard(candidate.fingerprint.tokens, listing_fp.tokens)
            if best is None or score > best[0]:
                best = (score, candidate)

        if best and best[0] >= AUTO_MATCH_THRESHOLD:
            product = best[1].product
            listing.product_id = product.id
            _record_match(db, listing, product, MatchMethod.FUZZY, round(best[0], 3))
            by_fuzzy += 1
            continue

        if best and best[0] >= REVIEW_THRESHOLD:
            # Candidato dudoso: se registra para revisión pero NO se aplica; la
            # publicación igual necesita un cluster propio para ser visible.
            _record_match(db, listing, best[1].product, MatchMethod.FUZZY, round(best[0], 3))
            queued += 1

        product = _create_product(db, listing)
        listing.product_id = product.id
        _record_match(db, listing, product, MatchMethod.FUZZY, 1.0)
        created += 1
        candidates.append(_candidate_from_product(product))

    db.commit()
    stats = MatchStats(
        listings_seen=seen,
        matched_by_catalog=by_catalog,
        matched_by_fuzzy=by_fuzzy,
        products_created=created,
        queued_for_review=queued,
    )
    logger.info("matching: %s", stats)
    return stats

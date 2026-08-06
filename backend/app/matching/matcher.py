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

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.enums import MatchMethod
from app.matching.normalize import (
    extract_generation_numbers,
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
    generations: frozenset[str]
    screen_inches: float | None


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
        generations=extract_generation_numbers(title),
        screen_inches=extract_screen_inches(title),
    )


def _conflicts(a: _Fingerprint, b: _Fingerprint) -> bool:
    """Diferencias que descartan el match sin importar cuánto se parezcan los títulos."""
    if a.brand and b.brand and normalize_text(a.brand) != normalize_text(b.brand):
        return True
    if a.capacity_gb is not None and b.capacity_gb is not None and a.capacity_gb != b.capacity_gb:
        return True
    # Un televisor de 50" y uno de 55" de la misma linea comparten el codigo de
    # fabricante (`50PUD7309` / `PUD7309`), asi que sin esta guarda se agrupaban y la
    # ficha comparaba dos productos de tamano distinto.
    if (
        a.screen_inches is not None
        and b.screen_inches is not None
        and abs(a.screen_inches - b.screen_inches) > 0.5
    ):
        return True
    # "iPhone 13" vs "iPhone 13 Pro Max": mismos tokens casi todos, producto distinto.
    if a.variants != b.variants:
        return True
    # "iPhone 13" vs "iPhone 14": el número de generación es lo ÚNICO que los separa
    # (Jaccard 0.5, por encima del umbral). Sin esta guarda el cluster del iPhone 13
    # se comía al 14 y al 15 y la comparación de precios quedaba mintiendo.
    #
    # La condición es que CADA lado tenga un número que el otro no tiene, no que la
    # intersección sea vacía: "iPhone 15 Pro Max 256 GB 8" y "iPhone 16 Pro Max 256 GB 8"
    # comparten el 8 y con la regla de intersección se fusionaban igual. Al mismo tiempo,
    # que un título traiga números de más ("Ryzen 3 15,6") no puede descartar el match si
    # el otro es un subconjunto.
    if (a.generations - b.generations) and (b.generations - a.generations):
        return True
    # Códigos de fabricante disjuntos = dos productos distintos... salvo que una de las
    # dos tiendas haya publicado ADEMAS el código del chip ("7520u") y la otra no: ahí
    # los sets son disjuntos sin que los productos lo sean. Por eso el conflicto exige
    # que ninguno de los códigos de un lado aparezca dentro de un código del otro.
    if a.model_codes and b.model_codes and not _codes_overlap(a.model_codes, b.model_codes):
        return True
    return False


#: Longitud mínima para aceptar una coincidencia por contención. Con códigos cortos la
#: contención es puro ruido: `800w` está dentro de `2800w` sin que tengan nada que ver.
#: Un código de 6+ caracteres contenido en otro sí es señal (`fc0235la` ⊂ `15fc0235la`).
_MIN_CONTAINMENT_LENGTH = 6


def _codes_overlap(a: frozenset[str], b: frozenset[str]) -> bool:
    """Hay un código en común, exacto o por contención (`15fc0235la` ⊃ `fc0235la`)."""
    if a & b:
        return True
    return any(
        (x in y or y in x) and min(len(x), len(y)) >= _MIN_CONTAINMENT_LENGTH
        for x in a
        for y in b
    )


def _shares_model_code(a: _Fingerprint, b: _Fingerprint) -> bool:
    """Ambos títulos traen el mismo código de fabricante.

    Es la señal más fuerte que existe sin id de catálogo, y por sí sola alcanza para
    agrupar: dos tiendas que escriben `UN50U8000F` están hablando del mismo televisor
    aunque el resto del título no se parezca en nada. Antes esto solo servía para
    DESCARTAR, así que "Smart TV Samsung UN50U8000F 50 pulgadas 4K" y
    'Samsung Smart TV 50" UN50U8000F UHD' quedaban en clusters separados (Jaccard 0.33,
    debajo del umbral) — dos productos de una tienda cada uno en vez de uno comparable.
    """
    return bool(a.model_codes) and bool(b.model_codes) and _codes_overlap(a.model_codes, b.model_codes)


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

    # Los recortes siguen los largos declarados en `app/models/product.py`: Postgres
    # aborta la transaccion entera con `StringDataRightTruncation` (SQLite no dice nada),
    # y como el matcher corre en una sola transaccion eso perderia toda la corrida.
    model = guess_model(listing.title, brand)
    # `catalog_product_id` es UNIQUE: si ya existe un producto con este id, se deja en
    # NULL en vez de reventar la corrida entera. Que llegue acá significa que la vía
    # determinística no lo encontró, así que el producto existente no era candidato
    # válido (quedó huérfano, o va a borrarse al final de un re-matching).
    catalog_id = listing.catalog_product_id
    if catalog_id and db.scalar(
        select(Product.id).where(Product.catalog_product_id == catalog_id)
    ):
        catalog_id = None

    product = Product(
        canonical_title=listing.title[:512],
        brand=(brand.upper() if len(brand) <= 3 else brand.capitalize())[:128] if brand else None,
        model=model[:128] if model else None,
        category=None,
        # El id de catalogo de la publicacion, cuando la fuente lo provee: hace que la
        # proxima publicacion con el mismo id caiga en este producto por la via
        # deterministica en vez de por similitud de titulos.
        catalog_product_id=catalog_id,
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


def _delete_orphan_products(db: Session) -> None:
    """Borra los productos que quedaron sin ninguna publicación tras un re-matching."""
    orphan_ids = db.scalars(
        select(Product.id).outerjoin(Listing, Listing.product_id == Product.id).where(
            Listing.id.is_(None)
        )
    ).all()
    if not orphan_ids:
        return
    db.execute(delete(ProductMatch).where(ProductMatch.product_id.in_(orphan_ids)))
    db.execute(delete(Product).where(Product.id.in_(orphan_ids)))


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

    if only_unmatched:
        candidates = [
            _candidate_from_product(product) for product in db.scalars(select(Product)).all()
        ]
    else:
        # Re-evaluación completa: los clusters se reconstruyen desde cero. Sin esto,
        # cada publicación encontraba el producto singleton que el propio matcher le
        # había creado antes (cuyo `canonical_title` ES su título, o sea Jaccard 1.0),
        # se re-asignaba a sí misma y `--all` no fusionaba NADA. Los productos que
        # queden vacíos se borran al final.
        candidates = []
        for listing in listings:
            listing.product_id = None
        db.flush()

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

        catalog_id = listing.catalog_product_id
        if catalog_id:
            candidate = by_catalog_id.get(catalog_id)
            if candidate is None:
                # También puede existir en la base sin estar entre los candidatos en
                # memoria: en modo `--all` los candidatos arrancan vacíos, pero los
                # productos viejos siguen ahí hasta que se borran los huérfanos al final.
                # Sin esta consulta se creaba un producto nuevo con el mismo
                # `catalog_product_id` y saltaba el UNIQUE de la columna.
                existing = db.scalar(
                    select(Product).where(Product.catalog_product_id == catalog_id)
                )
                if existing is not None:
                    candidate = _candidate_from_product(existing)
                    candidates.append(candidate)
                    by_catalog_id[catalog_id] = candidate
            if candidate is not None:
                product = candidate.product
                listing.product_id = product.id
                _record_match(db, listing, product, MatchMethod.CATALOG_ID, 1.0)
                by_catalog += 1
                continue

        best: tuple[float, _Candidate] | None = None
        exact: _Candidate | None = None
        for candidate in candidates:
            if _conflicts(candidate.fingerprint, listing_fp):
                continue
            # El código de fabricante compartido gana sin mirar el Jaccard: dos tiendas
            # que escriben el mismo `UN50U8000F` hablan del mismo televisor aunque
            # ordenen el título completamente distinto.
            if exact is None and _shares_model_code(candidate.fingerprint, listing_fp):
                exact = candidate
            score = jaccard(candidate.fingerprint.tokens, listing_fp.tokens)
            if best is None or score > best[0]:
                best = (score, candidate)

        if exact is not None:
            listing.product_id = exact.product.id
            _record_match(db, listing, exact.product, MatchMethod.FUZZY, 0.95)
            by_fuzzy += 1
            continue

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
        # Sin `_record_match`: no hubo comparación con nada, y registrarlo con
        # confianza 1.0 llenaba la cola de revisión de singletons sin evidencia,
        # justo en el extremo que el índice ordena como "más confiable".
        created += 1
        new_candidate = _candidate_from_product(product)
        candidates.append(new_candidate)
        # El producto recién creado también tiene que entrar al índice por catalog id,
        # o la segunda publicación con el mismo id no lo encuentra y cae a similitud.
        if product.catalog_product_id:
            by_catalog_id.setdefault(product.catalog_product_id, new_candidate)

    if not only_unmatched:
        # `flush` antes de buscar huérfanos: las reasignaciones de `product_id` viven
        # solo en la sesión hasta acá, y sin bajarlas el LEFT JOIN ve todos los
        # productos como vacíos y los borra a todos.
        db.flush()
        _delete_orphan_products(db)

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

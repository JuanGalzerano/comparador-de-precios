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
import math
import re
from collections import defaultdict
from decimal import Decimal
from typing import Any, Literal

import httpx
from fastapi import APIRouter, Query
from sqlalchemy import ColumnElement, and_, case, func, literal, or_, select

from app.api.deps import DbSession
from app.enums import ItemCondition
from app.models.listing import Listing
from app.models.product import Product
from app.models.retailer_source import RetailerSource
from app.scoring.score import score_listings
from app.schemas.search import ProductClusterOut, SearchResponse
from app.services import ml_token
from app.services.live_search import fetch_live, should_fetch
from app.services.maintenance import touch_products

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
    """Complemento en vivo desde la API de ML. Nunca propaga errores.

    TODO el cuerpo va adentro del `try`, incluido el parseo: la API puede responder
    200 con HTML (pagina de mantenimiento o challenge de un WAF), y ahi `resp.json()`
    levanta `JSONDecodeError`. Con el parseo afuera del `try` eso era un 500 en `/search`,
    que es la home del sitio — justo el caso que este bloque decia degradar.
    """
    headers = {"Accept": "application/json"}
    # La API de ML pasó a exigir OAuth: sin token responde 403 y esta funcion devuelve
    # vacio. El token se obtiene y renueva solo. Ver PENDIENTE.md.
    if token := ml_token.get_token():
        headers["Authorization"] = f"Bearer {token}"

    try:
        with httpx.Client(timeout=_ML_TIMEOUT) as client:
            resp = client.get(
                _ML_SEARCH_URL,
                params={"q": query, "limit": min(limit, 50), "sort": "relevance"},
                headers=headers,
            )
            resp.raise_for_status()

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
                    retailer_count=1,
                    retailer_names=["MercadoLibre"],
                    min_final_price=price,
                    max_final_price=price,
                    best_score=_ml_score(item),
                    permalink=item.get("permalink"),
                )
            )
        return results
    except Exception as exc:
        logger.warning("ML live search failed for %r: %s", query, exc)
        return []


SearchSort = Literal["price", "retailers", "spread"]


def _escapar_like(texto: str) -> str:
    """`%` y `_` del usuario son comodines de LIKE: sin escaparlos, buscar "50%" matchea
    cualquier cosa que empiece con 50 y "a_b" matchea "axb"."""
    return texto.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _relevancia(tokens: list[str]) -> ColumnElement[Any]:
    """Qué tan bien responde un producto a lo que se buscó. Menor es mejor.

    Ordenar solo por precio da un resultado absurdo: buscando "smart tv", un **soporte**
    de smart tv a $8.000 le gana a un televisor de $600.000. El accesorio es más barato
    por definición, así que siempre sale primero.

    La señal que los separa es dónde arranca el título. Un televisor se llama "Smart TV
    55 Philco"; un soporte se llama "Soporte para Smart TV" — menciona lo buscado, pero
    no empieza con eso. Los accesorios casi siempre anteponen su propio sustantivo:
    soporte, funda, cable, adaptador.

    Tres escalones:

    0. El título empieza con la búsqueda completa ("smart tv...").
    1. El título empieza con la primera palabra ("smart...").
    2. Todo lo demás: lo menciona, pero en el medio.

    Dentro de cada escalón sigue mandando el criterio elegido (precio, tiendas, spread),
    así que no se pierde nada de lo anterior: el más barato de los televisores de verdad
    queda primero.
    """
    if not tokens:
        return literal(0)

    frase = _escapar_like(" ".join(tokens))
    primera = _escapar_like(tokens[0])
    return case(
        (Product.canonical_title.ilike(f"{frase}%", escape="\\"), 0),
        (Product.canonical_title.ilike(f"{primera}%", escape="\\"), 1),
        else_=2,
    )


def _order_by(sort: SearchSort, tokens: list[str] | None = None) -> list[ColumnElement[Any]]:
    """Orden del listado de clusters.

    - `price` (default): el cluster más barato primero, el orden histórico.
    - `retailers`: primero los productos que se pueden comparar entre más tiendas —
      es donde el comparador realmente sirve.
    - `spread`: mayor diferencia entre la publicación más cara y la más barata del
      mismo producto: donde elegir bien ahorra más plata.

    Cuando hay término de búsqueda, la relevancia manda por encima de todo: ver
    `_relevancia`.
    """
    cheapest = func.min(Listing.final_price)
    retailers = func.count(func.distinct(Listing.retailer_source_id))
    spread = func.max(Listing.final_price) - func.min(Listing.final_price)

    if sort == "retailers":
        criterio = [retailers.desc(), spread.desc(), Product.id.asc()]
    elif sort == "spread":
        criterio = [spread.desc(), retailers.desc(), Product.id.asc()]
    else:
        criterio = [cheapest.asc(), Product.id.asc()]

    if tokens:
        return [_relevancia(tokens).asc(), *criterio]
    return criterio


def _build_filters(
    *,
    q: str | None,
    tokens: list[str] | None = None,
    category: str | None,
    condition: Literal["all", "new", "used", "refurbished", "unknown"],
) -> list[ColumnElement[bool]]:
    """Predicados sobre `listing`/`product` que definen el set "matcheado".

    Se usan tanto para el agregado (resumen de cluster) como para traer las
    publicaciones individuales que entran en ese resumen: tienen que ser EXACTAMENTE
    los mismos, o el `best_score` quedaria calculado sobre un set distinto del que
    dice `listing_count`.
    """
    filters: list[ColumnElement[bool]] = [
        # Lo que no se puede comprar no entra a la comparacion. Las tiendas dejan
        # productos descontinuados en su catalogo con el precio de hace anios — Jumbo
        # publica un LED 50" a $13.499 sin stock — y como se ordena por precio, esos
        # zombis aparecian como la mejor oferta del sitio.
        Listing.unavailable_since.is_(None),
    ]
    if condition != "all":
        filters.append(Listing.condition == ItemCondition(condition))
    if category:
        filters.append(func.lower(Product.category) == category.strip().lower())
    # `is not None` y no un `if` a secas: evaluar la verdad de una expresion de
    # SQLAlchemy levanta TypeError.
    text_filter = _text_filter(q, tokens)
    if text_filter is not None:
        filters.append(text_filter)
    return filters


#: Palabras que no discriminan nada: aparecen en cualquier titulo y solo hacen ruido.
_STOPWORDS = frozenset(
    {"de", "del", "la", "el", "los", "las", "un", "una", "con", "para", "por", "y", "o", "en", "a"}
)

#: Tope de tokens que se consideran. Un slug de MercadoLibre puede traer 12 palabras;
#: mas alla de esto no se gana precision y la consulta se vuelve enorme.
_MAX_TOKENS = 8

#: Fraccion de las palabras de contexto que tiene que matchear. 0.4 sobre 7 palabras
#: pide 3: suficiente para excluir otro producto, laxo para tolerar que cada tienda
#: titule distinto.
_CONTEXT_RATIO = 0.4

_SEARCHABLE_COLUMNS = (
    Product.canonical_title,
    Product.brand,
    Product.model,
    Listing.title,
)


def _tokenize(q: str) -> list[str]:
    """Palabras utiles de la consulta, sin stopwords ni repetidas, en orden."""
    tokens: list[str] = []
    for raw in re.split(r"[^0-9a-zA-ZÀ-ſ]+", q.lower()):
        if len(raw) < 2 or raw in _STOPWORDS or raw in tokens:
            continue
        tokens.append(raw)
        if len(tokens) == _MAX_TOKENS:
            break
    return tokens


def _matches_token(token: str) -> ColumnElement[bool]:
    """El token aparece en alguna de las columnas de texto."""
    # `%` y `_` del usuario son comodines de LIKE: sin escaparlos, buscar "50%" matchea
    # cualquier cosa que empiece con 50 y "a_b" matchea "axb".
    escaped = token.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    like = f"%{escaped}%"
    return or_(*[col.ilike(like, escape="\\") for col in _SEARCHABLE_COLUMNS])


def _is_model_number(token: str) -> bool:
    """Numero de modelo: puro digito y de 3 cifras para arriba (5080, 4090, 128).

    Se exigen 3 cifras porque con dos (el `13` de "iphone 13") el numero aparece dentro
    de cualquier otro codigo y no discrimina. Los alfanumericos tipo `16gb` o `gddr7` NO
    entran a proposito: cada tienda los escribe distinto (`16GB`, `16 GB`, `16g`) y
    hacerlos obligatorios dejaria afuera al mismo producto.
    """
    return token.isdigit() and len(token) >= 3


def _text_filter(q: str | None, tokens: list[str] | None = None) -> ColumnElement[bool] | None:
    """Filtro de texto tolerante a titulos largos.

    El problema que resuelve: pegar el link de un producto produce una consulta como
    "placa de video nvidia gigabyte geforce rtx 5080 windforce oc 16g gddr7". Buscar esa
    frase entera con `ILIKE '%...%'` no matchea nada, porque ninguna otra tienda titula
    igual — y el usuario ve "sin resultados" para un producto que el comparador tiene.

    La regla, entonces:

    - **Los numeros de modelo son obligatorios.** Sin esto, aflojar la busqueda haria que
      pedir una 5080 devuelva una 5070 de la misma marca, que es peor que no devolver
      nada.
    - **El resto es contexto**: alcanza con que matchee una fraccion. Asi entra el mismo
      producto publicado como "Placa de Video Gigabyte GeForce RTX 5080 16GB".
    """
    if tokens is None:
        if not q or not q.strip():
            return None
        tokens = _tokenize(q)
    if not tokens:
        return None

    obligatorios = [t for t in tokens if _is_model_number(t)]
    contexto = [t for t in tokens if not _is_model_number(t)]

    condiciones: list[ColumnElement[bool]] = [_matches_token(t) for t in obligatorios]

    if contexto:
        # El piso es 2 (no 1) cuando hay varias palabras: con una sola coincidencia,
        # una palabra generica como "video" arrastra medio catalogo.
        piso = 1 if len(contexto) == 1 else 2
        minimo = max(piso, math.ceil(len(contexto) * _CONTEXT_RATIO))
        if minimo >= len(contexto):
            # Consulta corta: pedirlas todas es lo mismo y evita el `CASE` de mas.
            condiciones.extend(_matches_token(t) for t in contexto)
        else:
            aciertos = sum(case((_matches_token(t), 1), else_=0) for t in contexto)
            condiciones.append(aciertos >= minimo)

    return and_(*condiciones)



#: Hasta cuantas veces se afloja la busqueda antes de rendirse. Cada intento es una
#: consulta mas a la base, asi que no es gratis; con 4 se cubre desde un slug de 8
#: palabras hasta las 2 primeras.
_MAX_RELAXATIONS = 4


def _relaxations(tokens: list[str]) -> list[list[str]]:
    """Versiones progresivamente mas cortas de la consulta, de mas a menos exigente.

    Se sueltan palabras **del final**, no del principio, porque los titulos de producto
    van de lo general a lo especifico: "placa de video nvidia gigabyte geforce rtx 5080
    windforce" empieza por lo que el usuario reconoce y termina en detalles del
    fabricante. Soltando desde atras, la primera version que devuelve algo sigue siendo
    del rubro que se pidio.

    Mostrar las placas de video Nvidia es mas util que una pantalla vacia: el usuario ve
    que el producto exacto no esta pero el comparador funciona, y de paso encuentra
    alternativas.
    """
    # Las palabras de una o dos letras se descartan al aflojar: como se busca por
    # subcadena, "no" matchea "Notebook" y la busqueda relajada devolveria basura.
    utiles = [t for t in tokens if len(t) >= 3]

    intentos: list[list[str]] = []
    corte = len(utiles) - 1
    while corte >= 2 and len(intentos) < _MAX_RELAXATIONS:
        intentos.append(utiles[:corte])
        corte -= 1
    return intentos

def _live_term(q: str) -> str:
    """Termino recortado para preguntarle a las tiendas.

    Los adapters buscan en el buscador de cada tienda, que tampoco entiende una frase de
    doce palabras: se le manda el slug entero a Fravega y devuelve cero. Se quedan los
    numeros de modelo y las primeras palabras de contexto, que es lo que una persona
    tipearia.
    """
    tokens = _tokenize(q)
    if len(tokens) <= 4:
        return q.strip()

    contexto = [t for t in tokens if not _is_model_number(t)][:3]
    recortado = [t for t in tokens if _is_model_number(t) or t in contexto]
    return " ".join(recortado)


#: Cuántos clusters tiene que tener ya la base para considerar que la búsqueda está
#: cubierta y no hace falta molestar a las tiendas.
_LIVE_ENOUGH_RESULTS = 5


def _live_items_to_clusters(items: list) -> list[ProductClusterOut]:
    """Convierte publicaciones sin guardar en clusters de respuesta.

    Solo se usa en el modo degradado (base llena): se agrupa por título normalizado, que
    es una aproximación al matcher — no hay `product` en la base contra el cual agrupar.
    """
    from app.matching.normalize import normalize_text

    by_key: dict[str, list] = defaultdict(list)
    for item in items:
        by_key[normalize_text(item.title)].append(item)

    clusters: list[ProductClusterOut] = []
    for i, (_, group) in enumerate(by_key.items()):
        prices = [it.price + (it.shipping_cost or Decimal(0)) for it in group]
        first = group[0]
        clusters.append(
            ProductClusterOut(
                id=-(i + 1),  # efímero: no existe en la base
                canonical_title=first.title,
                brand=first.product_hint.brand if first.product_hint else None,
                model=None,
                category=None,
                catalog_product_id=None,
                listing_count=len(group),
                retailer_count=len({it.source_slug for it in group}),
                retailer_names=sorted({it.source_slug for it in group}),
                min_final_price=min(prices),
                max_final_price=max(prices),
                best_score=50,
                permalink=first.permalink,
            )
        )
    clusters.sort(key=lambda c: c.min_final_price)
    return clusters


def _maybe_fetch_live(
    db: DbSession,
    term: str,
    *,
    category: str | None,
    condition: str,
) -> list[ProductClusterOut]:
    """Devuelve clusters efímeros si la base está llena; lista vacía en el caso normal."""
    """Consulta las tiendas en vivo si la base no tiene suficiente para este término.

    Se hace ANTES de la query principal para que los resultados nuevos entren en la
    misma respuesta. El costo (~2s) lo paga solo la primera persona que busca algo
    nuevo; después queda cacheado en la base.
    """
    existing = db.execute(
        select(func.count(func.distinct(Listing.product_id)))
        .select_from(Listing)
        .join(Product, Listing.product_id == Product.id)
        .where(*_build_filters(q=term, category=category, condition=condition))  # type: ignore[arg-type]
    ).scalar_one()

    if existing >= _LIVE_ENOUGH_RESULTS:
        return []
    if not should_fetch(term):
        return []

    try:
        result = fetch_live(db, term)
    except Exception as exc:
        # Una búsqueda en vivo fallida nunca puede romper la búsqueda: se sigue con lo
        # que haya en la base.
        db.rollback()
        logger.warning("live search failed for %r: %s", term, exc)
        return []

    if not result.persisted and result.items:
        return _live_items_to_clusters(result.items)
    return []


@router.get("", response_model=SearchResponse)
def search(
    db: DbSession,
    q: str | None = Query(default=None, description="Termino de busqueda libre."),
    category: str | None = Query(default=None, description="Categoria canonica de Cotejo."),
    condition: Literal["all", "new", "used", "refurbished", "unknown"] = Query(default="all"),
    sort: SearchSort = Query(
        default="price",
        description="price = más barato primero; retailers = más tiendas comparadas; "
        "spread = mayor diferencia de precio entre tiendas.",
    ),
    min_retailers: int = Query(
        default=1,
        ge=1,
        description="Mínimo de tiendas distintas que deben publicar el producto. "
        "Con 2, solo devuelve productos efectivamente comparables entre tiendas.",
    ),
    live: bool = Query(
        default=True,
        description="Si la base no tiene suficientes resultados, consultar las tiendas "
        "en vivo y guardar lo que llegue (agrega ~2s a esa primera búsqueda).",
    ),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> SearchResponse:
    # Caché bajo demanda: si nadie buscó esto antes, la base no lo tiene. En vez de
    # devolver "sin resultados", se les pregunta a las tiendas, se guarda y se sigue
    # normal — la próxima búsqueda del mismo término ya sale de la base.
    # Solo en la primera página y solo con término de búsqueda: paginar o navegar el
    # catálogo no puede disparar tráfico a las tiendas.
    ephemeral: list[ProductClusterOut] = []
    if live and q and q.strip() and page == 1:
        # Recortado: a las tiendas se les manda un termino que su buscador entienda,
        # no el slug de doce palabras que salio del link pegado.
        ephemeral = _maybe_fetch_live(db, _live_term(q), category=category, condition=condition)

    if ephemeral:
        # Modo degradado (base en la cuota): no hay nada que consultar en la base para
        # este término porque no se guardó. Se responde con lo que trajeron las tiendas.
        return SearchResponse(
            items=ephemeral[:page_size], page=page, page_size=page_size, total=len(ephemeral)
        )

    # --- Paso 1: agregado por producto (cuenta + min/max de `final_price`) ------
    # Un producto sin ninguna publicacion que matchee los filtros no debe aparecer:
    # el INNER JOIN implicito de `select_from(Listing).join(Product)` ya lo garantiza
    # (y de paso excluye publicaciones huerfanas con `product_id IS NULL`, que son un
    # estado valido de la ingesta pero no tienen cluster que mostrar).
    def _agregado(filtros: list[ColumnElement[bool]]):
        stmt = (
            select(
                Product.id.label("product_id"),
                func.count(Listing.id).label("listing_count"),
                func.count(func.distinct(Listing.retailer_source_id)).label("retailer_count"),
                func.min(Listing.final_price).label("min_final_price"),
                func.max(Listing.final_price).label("max_final_price"),
            )
            .select_from(Listing)
            .join(Product, Listing.product_id == Product.id)
            .where(*filtros)
            .group_by(Product.id)
        )
        if min_retailers > 1:
            stmt = stmt.having(
                func.count(func.distinct(Listing.retailer_source_id)) >= min_retailers
            )
        return stmt

    # Los tokens mandan dos cosas: qué se filtra y cómo se ordena. Cuando la cascada
    # afloja la búsqueda, la relevancia tiene que seguir a los tokens que ganaron.
    tokens_activos = _tokenize(q) if q and q.strip() else []
    filters = _build_filters(q=q, category=category, condition=condition)
    agg_stmt = _agregado(filters)
    total = db.execute(select(func.count()).select_from(agg_stmt.subquery())).scalar_one()

    # Cascada: si la busqueda exacta no encontro nada, se sueltan palabras del final
    # hasta que algo aparezca. Mostrar las placas de video Nvidia cuando se pidio un
    # modelo puntual es mas util que una pantalla vacia — pero hay que decirlo, o
    # parece que el buscador ignoro lo que se pidio (de ahi `relaxed_query`).
    relaxed_query: str | None = None
    if total == 0 and q and q.strip():
        for tokens in _relaxations(_tokenize(q)):
            filtros_aflojados = _build_filters(
                q=q, tokens=tokens, category=category, condition=condition
            )
            candidato = _agregado(filtros_aflojados)
            encontrados = db.execute(
                select(func.count()).select_from(candidato.subquery())
            ).scalar_one()
            if encontrados:
                agg_stmt, total, filters = candidato, encontrados, filtros_aflojados
                tokens_activos = tokens
                relaxed_query = " ".join(tokens)
                logger.info("busqueda aflojada: %r -> %r (%s resultados)", q, relaxed_query, total)
                break

    page_stmt = (
        agg_stmt.order_by(*_order_by(sort, tokens_activos))
        .limit(page_size)
        .offset((page - 1) * page_size)
    )
    agg_rows = db.execute(page_stmt).all()

    if not agg_rows:
        # Solo en la primera pagina: la busqueda live de ML no sabe paginar (no se le
        # pasa offset), asi que pedirla de nuevo en la pagina 2 devolvia LOS MISMOS
        # resultados y la paginacion no terminaba nunca.
        # `live` tambien manda aca: decia "no consultes las tiendas" y esta llamada lo
        # ignoraba, saliendo a la red igual.
        ml_items = (
            _ml_live_search(q.strip(), page_size) if live and q and q.strip() and page == 1 else []
        )
        return SearchResponse(
            items=ml_items, page=page, page_size=page_size, total=len(ml_items)
        )

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

    retailer_labels = {
        row.id: (row.display_name or row.slug)
        for row in db.execute(
            select(RetailerSource.id, RetailerSource.slug, RetailerSource.display_name)
        ).all()
    }

    items: list[ProductClusterOut] = []
    for row in agg_rows:
        product = products_by_id[row.product_id]
        cluster_listings = listings_by_product.get(row.product_id, [])
        scores = score_listings(cluster_listings)
        best_score = max(scores) if scores else 0
        cluster_retailers = sorted(
            {
                retailer_labels.get(listing.retailer_source_id, "")
                for listing in cluster_listings
            }
            - {""}
        )
        items.append(
            ProductClusterOut(
                id=product.id,
                canonical_title=product.canonical_title,
                brand=product.brand,
                model=product.model,
                category=product.category,
                catalog_product_id=product.catalog_product_id,
                listing_count=row.listing_count,
                retailer_count=len(cluster_retailers),
                retailer_names=cluster_retailers,
                min_final_price=Decimal(row.min_final_price),
                max_final_price=Decimal(row.max_final_price),
                best_score=best_score,
            )
        )

    # Registrar que estos productos se usaron: es lo que le permite a la evicción
    # distinguir un producto que se busca seguido de uno que nadie miró nunca.
    touch_products(db, [item.id for item in items if item.id > 0])

    # Complementar con ML live si la DB no llena la página (solo la primera: ver arriba).
    # `live` manda acá también: es el caso común (la base casi nunca llena la página),
    # así que sin este chequeo `live=false` seguía saliendo a la red igual.
    if live and q and q.strip() and page == 1 and len(items) < page_size:
        ml_items = _ml_live_search(q.strip(), page_size - len(items))
        items.extend(ml_items)
        total += len(ml_items)

    return SearchResponse(
        items=items, page=page, page_size=page_size, total=total, relaxed_query=relaxed_query
    )

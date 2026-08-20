"""DTOs del contrato `SourceAdapter`.

Estos tipos son la frontera entre "traer datos de una fuente" y "escribir en la base".
Ningun tipo de aca importa SQLAlchemy: un adapter tiene que poder correr en un proceso que
no tiene acceso a la base (p.ej. un spider de Scrapy que emite `NormalizedListingInput`
por un pipeline, o un test unitario contra un fixture HTTP).

Diseno pensado contra las cuatro formas de fuente del plan, que son genuinamente distintas:

| Fuente            | Forma de traer datos                              | Modo        |
|-------------------|---------------------------------------------------|-------------|
| MercadoLibre      | `GET /sites/MLA/search?q=...` paginado             | `search`    |
|                   | `GET /items?ids=MLA1,MLA2` (refresco de precios)   | `refresh`   |
| VTEX (Fravega...) | `GET /api/catalog_system/pub/products/search?ft=`  | `search`    |
| Precios Claros    | ZIP diario completo, sin concepto de "query"       | `batch`     |
| Scrapy            | spider sobre la busqueda del sitio                 | `search`    |

Por eso `fetch_listings` NO recibe un `SearchQuery`: recibe un `FetchRequest`, union
discriminada por `mode`. Ver la justificacion completa en `app/adapters/base.py`.
"""

from __future__ import annotations

import enum
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.enums import ItemCondition, WarrantyType

JsonDict = dict[str, Any]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Capacidades
# ---------------------------------------------------------------------------


class FetchMode(str, enum.Enum):
    """Las tres formas de pedirle datos a una fuente.

    Un adapter declara cuales soporta en `capabilities.supported_modes`; el worker de
    ingesta consulta eso antes de despachar, en vez de asumir que toda fuente sabe buscar.
    """

    SEARCH = "search"  # busqueda por termino/categoria contra un endpoint vivo
    BATCH = "batch"  # volcado completo (ZIP/CSV/feed), sin termino de busqueda
    REFRESH = "refresh"  # re-lectura de publicaciones ya conocidas, por external_id


class SourceCapabilities(BaseModel):
    """Que sabe hacer y que sabe informar una fuente.

    No es decorativo: el score (`scoreOf`) trata NULL como "malo" en varios ejes
    (rating 0 -> 0.35, garantia desconocida -> 0). Saber que una fuente directamente NO
    informa reputacion de vendedor permite no castigar a sus publicaciones y ademas
    alimenta la pagina de transparencia y el panel admin.
    """

    model_config = ConfigDict(frozen=True)

    supported_modes: frozenset[FetchMode] = frozenset({FetchMode.SEARCH})

    #: Si el feed permite pedir "solo lo que cambio desde X" (`BatchRequest.since`).
    supports_incremental: bool = False
    #: Si `fetch_listings` puede devolver el catalogo completo sin termino de busqueda.
    supports_full_catalog: bool = False

    # Que campos del listing puede llegar a completar esta fuente.
    provides_seller_reputation: bool = False
    provides_ratings: bool = False
    provides_installments: bool = False
    provides_shipping_cost: bool = False
    provides_warranty: bool = False
    #: Si trae un id de catalogo compartido (habilita matching deterministico).
    provides_catalog_id: bool = False

    def supports(self, mode: FetchMode) -> bool:
        return mode in self.supported_modes


# ---------------------------------------------------------------------------
# Requests
# ---------------------------------------------------------------------------


class _FetchRequestBase(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    #: Tope duro de items a devolver en total (a traves de todas las paginas/archivos).
    #: `None` = sin tope; el adapter igual respeta su propio `max_pages` de config.
    max_results: int | None = Field(default=None, ge=1)

    #: Si traer los datos caros que viven en endpoints aparte (reputacion del vendedor,
    #: reviews, detalle del item). Un barrido de refresco de precios los apaga: en ML son
    #: 2 requests extra por publicacion y no cambian entre corridas.
    enrich: bool = True

    #: Parametros crudos especificos de la fuente que no vale la pena tipar aca
    #: (`salesChannel` de VTEX, `official_store_id` de ML...). Van al adapter tal cual.
    raw_params: JsonDict = Field(default_factory=dict)


class SearchQuery(_FetchRequestBase):
    """Busqueda contra un endpoint vivo (ML, VTEX, spider de busqueda).

    Todos los campos de filtro son opcionales: una fuente que soporte
    `capabilities.supports_full_catalog` acepta una `SearchQuery` sin `term` como
    "traeme todo lo de esta categoria".
    """

    mode: Literal[FetchMode.SEARCH] = FetchMode.SEARCH

    #: Termino de busqueda tal cual lo escribio el usuario ("iPhone 13 128GB").
    term: str | None = None
    #: Categoria en el vocabulario DE LA FUENTE (`MLA1051`, slug VTEX, ...).
    #: La traduccion desde la categoria canonica de Cotejo la hace el adapter con su config.
    category: str | None = None
    condition: ItemCondition | None = None

    #: Rango de precio en ARS. Sirve para dos cosas: filtro de usuario y particionar
    #: catalogos grandes en tramos cuando el endpoint tiene tope de paginacion.
    price_min: Decimal | None = Field(default=None, ge=0)
    price_max: Decimal | None = Field(default=None, ge=0)

    #: Tamano de pagina sugerido. El adapter lo recorta al maximo de su fuente
    #: (ML: 50, VTEX: 50 por `_from`/`_to`).
    page_size: int | None = Field(default=50, ge=1, le=200)
    #: Token opaco de continuacion, con el formato que use la fuente (offset, `scroll_id`,
    #: url de "siguiente"). Nadie fuera del adapter lo interpreta.
    cursor: str | None = None

    #: Orden pedido a la fuente. Es una pista, no una garantia: el orden real de la UI lo
    #: define `scoreOf()` sobre el set ya normalizado.
    sort: str | None = None

    @field_validator("term")
    @classmethod
    def _strip_term(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @model_validator(mode="after")
    def _check_price_range(self) -> "SearchQuery":
        if self.price_min is not None and self.price_max is not None:
            if self.price_min > self.price_max:
                raise ValueError("price_min no puede ser mayor que price_max")
        return self


class BatchRequest(_FetchRequestBase):
    """Ingesta de un volcado completo (Precios Claros/SEPA: un ZIP diario).

    No hay termino de busqueda porque la fuente no tiene busqueda: se baja el archivo y se
    itera. `resource_uri` en `None` significa "resolve la ultima version disponible", que
    es el caso normal del cron diario; se pasa explicito para reprocesar un dia puntual o
    un archivo ya descargado en disco (tests, backfill).
    """

    mode: Literal[FetchMode.BATCH] = FetchMode.BATCH

    #: Dia del snapshot a procesar. `None` = el mas reciente publicado.
    snapshot_date: date | None = None
    #: URL o path local del ZIP/CSV. `None` = lo resuelve el adapter.
    resource_uri: str | None = None
    #: Sub-conjuntos dentro del volcado (ids de comercio/sucursal en SEPA). Vacio = todos.
    partitions: list[str] = Field(default_factory=list)
    #: Categorias a conservar, en el vocabulario de la fuente. Vacio = todas.
    categories: list[str] = Field(default_factory=list)
    #: Solo registros modificados desde este momento. Requiere
    #: `capabilities.supports_incremental`; si no, el adapter lo ignora y avisa.
    since: datetime | None = None


class RefreshRequest(_FetchRequestBase):
    """Re-lectura de publicaciones que ya estan en `listing`, por `external_id`.

    Es el modo que alimenta `price_history` y detecta bajas de precio sin re-buscar todo.
    Existe como modo propio y no como una `SearchQuery` con filtros porque el acceso es
    distinto de verdad: ML tiene un endpoint batch dedicado (`/items?ids=...`, hasta 20 por
    request) y un scraper tiene que ir a la URL de cada publicacion, no a la de busqueda.
    """

    mode: Literal[FetchMode.REFRESH] = FetchMode.REFRESH

    external_ids: list[str] = Field(min_length=1)

    #: Sugerencia de tamano de lote. El adapter la recorta al maximo de su fuente.
    batch_size: int | None = Field(default=None, ge=1)

    #: Por defecto un refresco NO re-consulta reputacion/reviews: quiere precios.
    enrich: bool = False

    @field_validator("external_ids")
    @classmethod
    def _clean_ids(cls, value: list[str]) -> list[str]:
        cleaned = [item.strip() for item in value if item and item.strip()]
        if not cleaned:
            raise ValueError("external_ids no puede quedar vacio")
        # dedup preservando orden
        return list(dict.fromkeys(cleaned))


#: Lo que recibe `SourceAdapter.fetch_listings`. Union discriminada por `mode`:
#: pydantic elige la clase correcta sola al deserializar un payload de Celery.
FetchRequest = Annotated[
    Union[SearchQuery, BatchRequest, RefreshRequest],
    Field(discriminator="mode"),
]


# ---------------------------------------------------------------------------
# Raw
# ---------------------------------------------------------------------------


class RawFormat(str, enum.Enum):
    JSON = "json"
    HTML = "html"
    CSV_ROW = "csv_row"
    XML = "xml"


class RawListing(BaseModel):
    """Un registro tal como lo devolvio la fuente, sin interpretar.

    Se mantiene separado de `NormalizedListingInput` para que `fetch_listings` se pueda
    testear contra fixtures reales y para que `normalize` sea una funcion pura (mismo raw
    -> mismo normalizado), que es lo que permite re-normalizar historico cuando se corrige
    un parser sin volver a golpear la fuente.
    """

    model_config = ConfigDict(frozen=True)

    source_slug: str
    #: Puede venir en `None` si el id recien se puede extraer en `normalize`.
    external_id: str | None = None

    #: El documento en si. Para JSON/CSV, ya parseado a dict. Para HTML, ver `raw_text`.
    payload: JsonDict = Field(default_factory=dict)
    #: Cuerpo crudo cuando `payload` no alcanza (HTML de una ficha, linea CSV completa).
    raw_text: str | None = None
    raw_format: RawFormat = RawFormat.JSON

    #: Documentos secundarios ya resueltos por el adapter y necesarios para normalizar.
    #: En ML: `{"seller": {...}, "reviews": {...}}` (`/users/:id`, `/reviews/item/:id`).
    #: Existe para que `normalize` no haga I/O: todo lo que necesita ya viene en el raw.
    related: JsonDict = Field(default_factory=dict)

    fetched_at: datetime = Field(default_factory=_utcnow)

    #: De donde salio exactamente (URL con querystring, o
    #: `sepa_2026-07-30.zip#comercio_1/productos.csv:8412`). Va a los logs de error y hace
    #: reproducible cualquier bug de normalizacion.
    origin_ref: str | None = None


# ---------------------------------------------------------------------------
# Normalizado
# ---------------------------------------------------------------------------


class ProductHint(BaseModel):
    """Pistas de identidad del producto que trae la publicacion.

    NO se escribe en `listing`: lo consume el paso de matching para crear o encontrar el
    `product` canonico. Va aparte del resto de los campos justamente porque `listing` se
    inserta siempre y el matching puede correr despues, fallar, o ser revisado a mano.
    """

    model_config = ConfigDict(frozen=True)

    #: Id de catalogo de la fuente (`catalog_product_id` de ML). Habilita el camino
    #: deterministico de matching (`MatchMethod.CATALOG_ID`).
    catalog_product_id: str | None = None
    #: Identificadores globales: si dos fuentes coinciden en GTIN, el match es seguro.
    gtin: str | None = None
    sku: str | None = None
    mpn: str | None = None

    brand: str | None = None
    model: str | None = None
    #: Categoria canonica de Cotejo (no la de la fuente): el adapter ya tradujo.
    category: str | None = None

    #: Atributos normalizados para el matching fuzzy (capacidad, color, anio...).
    attributes: JsonDict = Field(default_factory=dict)


class NormalizedListingInput(BaseModel):
    """Una publicacion lista para hacer upsert en `listing`.

    Los nombres son exactamente los de la tabla `listing` (menos `product_id` y
    `retailer_source_id`, que los resuelve el worker: el adapter no conoce ids de la base).
    """

    model_config = ConfigDict(frozen=True)

    # --- Identidad ---------------------------------------------------------
    source_slug: str
    external_id: str
    title: str
    permalink: str
    condition: ItemCondition = ItemCondition.UNKNOWN

    # --- Precio ------------------------------------------------------------
    #: `gt=0` y no `ge=0`: una tienda que publica precio 0 no esta regalando el producto,
    #: esta diciendo "sin precio" (tipicamente sin stock). Aceptarlo lo convierte en el
    #: mas barato del grupo y el comparador anuncia un ahorro inventado — se vio con una
    #: RTX 5060 Ti de Cetrogar en $0 que ofrecia "ahorras hasta $1.506.799".
    #: El worker descarta el item y sigue: una publicacion rara no aborta la corrida.
    price: Decimal = Field(gt=0)
    #: 0 = envio gratis confirmado; `None` = la fuente no informa. La distincion importa:
    #: `scoreOf()` premia con 0.3 el envio en 0, y no seria honesto premiar un desconocido.
    shipping_cost: Decimal | None = Field(default=None, ge=0)
    #: ISO-4217. El schema de `listing` es mono-moneda (ARS): el worker rechaza cualquier
    #: otra cosa en vez de guardar numeros incomparables. Se declara aca, y no como columna,
    #: para que ese rechazo sea explicito y no un bug silencioso.
    currency: str = "ARS"

    # --- Financiacion ------------------------------------------------------
    installments_qty: int | None = Field(default=None, ge=0)
    installments_amount: Decimal | None = Field(default=None, ge=0)
    interest_free: bool | None = None

    # --- Vendedor ----------------------------------------------------------
    seller_name: str | None = None
    seller_id: str | None = None
    #: Normalizar a `app.enums.SELLER_LEVELS` cuando se pueda (es lo que espera el score).
    seller_level: str | None = None
    seller_sales: int | None = Field(default=None, ge=0)
    #: Nombre de la tienda oficial, o `None` si no lo es.
    official_store: str | None = None

    # --- Logistica ---------------------------------------------------------
    #: MercadoEnvios Full / envio gestionado por la plataforma (`l.full` en `scoreOf`).
    fulfillment: bool | None = None

    # --- Reputacion --------------------------------------------------------
    rating: Decimal | None = Field(default=None, ge=0, le=5)
    reviews_count: int | None = Field(default=None, ge=0)

    # --- Garantia ----------------------------------------------------------
    #: Ya parseado a meses desde el texto libre de `attributes[] WARRANTY_TIME`.
    warranty_months: int | None = Field(default=None, ge=0)
    warranty_type: WarrantyType = WarrantyType.UNKNOWN

    # --- Producto y trazabilidad -------------------------------------------
    product_hint: ProductHint = Field(default_factory=ProductHint)
    fetched_at: datetime = Field(default_factory=_utcnow)
    #: Copia de `RawListing.origin_ref`, para poder rastrear una fila rara hasta su origen.
    origin_ref: str | None = None

    @field_validator("currency")
    @classmethod
    def _upper_currency(cls, value: str) -> str:
        return value.strip().upper()

    @field_validator("external_id", "title", "permalink")
    @classmethod
    def _require_non_empty(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("no puede ser vacio")
        return cleaned

    @property
    def final_price(self) -> Decimal:
        """Mismo calculo que la columna generada `listing.final_price`."""
        return self.price + (self.shipping_cost or Decimal(0))


# ---------------------------------------------------------------------------
# Salud
# ---------------------------------------------------------------------------


class HealthState(str, enum.Enum):
    OK = "ok"
    DEGRADED = "degraded"  # responde pero mal (lento, datos incompletos, parser flojo)
    DOWN = "down"  # no responde / error
    BLOCKED = "blocked"  # 403, captcha, anti-bot: decision humana, no reintento
    UNKNOWN = "unknown"  # sin probe implementado


class HealthStatus(BaseModel):
    """Resultado de `SourceAdapter.health_check()`.

    Va derecho al panel admin y a `retailer_source.last_error`. `BLOCKED` se trata distinto
    de `DOWN` a proposito: un bloqueo no se reintenta solo, escala a revision de ToS.
    """

    model_config = ConfigDict(frozen=True)

    source_slug: str
    state: HealthState = HealthState.UNKNOWN
    checked_at: datetime = Field(default_factory=_utcnow)
    latency_ms: int | None = Field(default=None, ge=0)
    message: str | None = None
    details: JsonDict = Field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.state is HealthState.OK

    @classmethod
    def up(cls, source_slug: str, **kwargs: Any) -> "HealthStatus":
        return cls(source_slug=source_slug, state=HealthState.OK, **kwargs)

    @classmethod
    def down(cls, source_slug: str, message: str, **kwargs: Any) -> "HealthStatus":
        return cls(source_slug=source_slug, state=HealthState.DOWN, message=message, **kwargs)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


class AdapterConfig(BaseModel):
    """Mapea `retailer_source.config_json`.

    Base comun a todas las fuentes; cada adapter subclasea y agrega lo suyo
    (`VtexConfig.base_url` + `sales_channel`, `MercadoLibreConfig.site_id`, ...).
    `extra="allow"` a proposito: una fila de `retailer_source` puede llevar claves que un
    adapter viejo no conoce sin romper el arranque del worker.
    """

    model_config = ConfigDict(extra="allow")

    base_url: str | None = None
    timeout_seconds: float = 20.0
    #: Requests por segundo que se le permite a esta fuente. El plan pide reintentos y
    #: rate-limit en la capa de jobs (Celery), esto es el numero que ese worker respeta.
    rate_limit_rps: float | None = None
    max_retries: int = 3
    #: Tope de paginas por corrida, para no barrer un catalogo entero sin querer.
    max_pages: int | None = 20
    user_agent: str | None = None
    headers: dict[str, str] = Field(default_factory=dict)
    proxy_url: str | None = None

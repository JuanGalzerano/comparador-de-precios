"""Adapter de MercadoLibre.

API publica y sin autenticacion (no hace falta API key: si algun dia ML la exigiera,
iria a `Settings`/`.env`, nunca en un valor devuelto al frontend — ver `app/config.py`).

Endpoints usados (`site_id` default `MLA`, Argentina; ver `MercadoLibreConfig.site_id`):

    GET /sites/{site_id}/search?q=<term>&limit=<=50&offset=<n>   -> busqueda, paginada
    GET /items?ids=ID1,ID2,...                                    -> detalle batch (<=20 ids)
    GET /users/{seller_id}                                        -> seller_reputation
    GET /reviews/item/{item_id}                                   -> rating_average, total
    GET /sites/{site_id}                                           -> probe barata de salud

`normalize()` es pura (sin I/O): todo lo que necesita ya viene en `RawListing.payload`
(el item, de la busqueda o de `/items?ids=`) y `RawListing.related` (`{"seller": ...,
"reviews": ...}`, resueltos por `search()`/`fetch_by_ids()` antes de emitir el `RawListing`).

SUPUESTOS SOBRE EL FORMATO REAL DE LA API — a verificar con una llamada real antes de
produccion (marcados tambien en el reporte de esta tarea):

1. `seller_reputation.power_seller_status`: se asume que toma los valores literales
   `"platinum" | "gold" | "silver" | null`, que son EXACTAMENTE las tres primeras claves
   de `SELLER_LEVELS` (`app/enums.py`). Esto es lo documentado historicamente por la API
   de usuarios de ML (el badge "MercadoLider Platinum/Gold/Silver" que se ve en la UI).
   `null` se mapea a `"green"` (el cuarto nivel de `SELLER_LEVELS`) porque *no tener*
   badge de power seller es un estado real y conocido (vendedor nuevo/bajo volumen), no
   informacion faltante — de ahi que no se mapee a `None`.

   OJO: la API tambien expone `seller_reputation.level_id`, con valores tipo
   `"5_green"/"4_light_green"/"3_yellow"/"2_orange"/"1_red"` (el "termometro" de
   reclamos/cancelaciones). Es una dimension DISTINTA (calidad de servicio, no volumen/
   antiguedad) y sus nombres NO corresponden 1:1 con `platinum/gold/silver/green`, asi
   que deliberadamente no se usa para este mapeo (usar `level_id` como si fuera el mismo
   eje que `SELLER_LEVELS` seria peor que no mapear nada).

2. Texto libre de garantia (`item.warranty`, y a veces attributes `WARRANTY_TYPE`/
   `WARRANTY_TIME`): el parser (`_parse_warranty_months`/`_parse_warranty_type`) cubre
   los formatos mencionados en la tarea ("12 meses", "Sin garantia", "90 dias") mas
   variantes de "anios/oficial/fabrica/vendedor", por keyword matching. NO intenta
   cubrir cada frase posible (p.ej. "garantia extendida", rangos "entre 3 y 6 meses"):
   lo que no matchea queda en `warranty_months=None`, `WarrantyType.UNKNOWN`, que es el
   estado honesto ("no se pudo interpretar") y no un valor inventado.

3. `official_store`: el schema espera el NOMBRE de la tienda oficial (ver comentario en
   `app/models/listing.py`). La API solo da `official_store_id` (un int) en el item;
   resolver el nombre real necesitaria golpear `/official_stores/{id}` aparte. Como
   aproximacion barata (sin ese request extra) se usa el nickname del vendedor cuando
   `official_store_id` no es `None` — funciona razonablemente porque los vendedores de
   tienda oficial casi siempre publican con el nombre de la tienda como nickname, pero
   es una aproximacion, no el dato real.

4. `shipping_cost`: la API no expone un costo de envio real y estable en `/search` ni en
   `/items` (el costo depende de CP del comprador y sale de otro endpoint de
   estimacion, fuera de alcance de esta tarea). Por eso solo se completa el caso
   `shipping.free_shipping == True -> Decimal(0)`; en cualquier otro caso queda `None`
   ("la fuente no informa"), que es literalmente el contrato de `NormalizedListingInput`.
"""

from __future__ import annotations

import re
import time
from collections.abc import Iterable, Iterator
from decimal import Decimal, InvalidOperation
from typing import Any, ClassVar

import httpx
from pydantic import ValidationError

from app.adapters.base import BaseSourceAdapter
from app.adapters.errors import (
    AuthenticationError,
    BlockedBySource,
    NormalizationError,
    RateLimited,
    SourceUnavailable,
)
from app.adapters.registry import register_adapter
from app.adapters.types import (
    AdapterConfig,
    FetchMode,
    HealthState,
    HealthStatus,
    NormalizedListingInput,
    ProductHint,
    RawListing,
    RefreshRequest,
    SearchQuery,
    SourceCapabilities,
)
from app.enums import SELLER_LEVELS, ItemCondition, SourceKind, WarrantyType

JsonDict = dict[str, Any]

DEFAULT_BASE_URL = "https://api.mercadolibre.com"
#: Tope real de la API para `/items?ids=` y para `limit` de `/search`.
MAX_ITEMS_PER_BATCH = 20
MAX_SEARCH_PAGE_SIZE = 50


class MercadoLibreConfig(AdapterConfig):
    """`config_json` de la fila `retailer_source` para MercadoLibre.

    `site_id`: sitio de ML (`MLA` Argentina, `MLB` Brasil, ...). Default `MLA` porque
    Cotejo es AR-only por ahora (mono-moneda ARS, ver `NormalizedListingInput.currency`).
    """

    site_id: str = "MLA"


def _chunk(items: Iterable[str], size: int) -> Iterator[list[str]]:
    buffer: list[str] = []
    for item in items:
        buffer.append(item)
        if len(buffer) == size:
            yield buffer
            buffer = []
    if buffer:
        yield buffer


# ---------------------------------------------------------------------------
# Parser de garantia (best-effort, ver punto 2 del docstring del modulo)
# ---------------------------------------------------------------------------

_MONTHS_RE = re.compile(r"(\d+)\s*mes(?:es)?\b", re.IGNORECASE)
_YEARS_RE = re.compile(r"(\d+)\s*a[ñn]o(?:s)?\b", re.IGNORECASE)
_DAYS_RE = re.compile(r"(\d+)\s*d[ií]as?\b", re.IGNORECASE)


def _parse_warranty_months(*texts: str | None) -> int | None:
    """Extrae una cantidad de meses de texto libre tipo '12 meses', '90 dias', '1 año'.

    No exhaustivo a proposito (ver punto 2 del docstring del modulo): si ningun patron
    matchea, devuelve `None` ("no se pudo interpretar"), no 0.
    """
    for text in texts:
        if not text:
            continue
        match = _MONTHS_RE.search(text)
        if match:
            return int(match.group(1))
        match = _YEARS_RE.search(text)
        if match:
            return int(match.group(1)) * 12
        match = _DAYS_RE.search(text)
        if match:
            days = int(match.group(1))
            return max(1, round(days / 30))
    return None


def _parse_warranty_type(*texts: str | None) -> WarrantyType:
    """Best-effort: busca keywords tipicas de ML en español. Ver punto 2 del modulo."""
    haystack = " ".join(t for t in texts if t).lower()
    if not haystack.strip():
        return WarrantyType.UNKNOWN
    if "sin garant" in haystack:
        return WarrantyType.SIN
    if "fabrica" in haystack or "fábrica" in haystack or "oficial" in haystack:
        return WarrantyType.OFICIAL
    if "vendedor" in haystack:
        return WarrantyType.VENDEDOR
    return WarrantyType.UNKNOWN


@register_adapter("mercadolibre")
class MercadoLibreAdapter(BaseSourceAdapter):
    """Adapter de la API publica de MercadoLibre.

    Soporta `search` (busqueda paginada) y `refresh` (relectura por `external_id` via
    `/items?ids=`, hasta `MAX_ITEMS_PER_BATCH` por request). No soporta `batch`: ML no
    tiene concepto de "volcado completo sin termino de busqueda" (eso es Precios Claros).
    """

    kind: ClassVar[SourceKind] = SourceKind.API
    config_model: ClassVar[type[AdapterConfig]] = MercadoLibreConfig
    capabilities: ClassVar[SourceCapabilities] = SourceCapabilities(
        supported_modes=frozenset({FetchMode.SEARCH, FetchMode.REFRESH}),
        supports_incremental=False,
        supports_full_catalog=False,
        provides_seller_reputation=True,
        provides_ratings=True,
        provides_installments=True,
        # Solo confirmamos el caso "envio gratis"; el costo real cuando NO es gratis no
        # esta disponible sin un endpoint de estimacion aparte (ver punto 4 del modulo).
        provides_shipping_cost=True,
        provides_warranty=True,
        provides_catalog_id=True,
    )

    config: MercadoLibreConfig  # narrowing para autocompletado; el runtime type ya lo valida

    # --- HTTP ---------------------------------------------------------------

    def _base_url(self) -> str:
        return self.config.base_url or DEFAULT_BASE_URL

    def _client(self) -> httpx.Client:
        headers = dict(self.config.headers)
        if self.config.user_agent:
            headers.setdefault("User-Agent", self.config.user_agent)
        # OAuth 2.0 Client Credentials. Ver MERCADOLIBRE_API.md.
        # Ponés ML_ACCESS_TOKEN en .env y el adapter lo inyecta automáticamente.
        from app.config import settings
        if token := settings.ml_access_token:
            headers["Authorization"] = f"Bearer {token}"
        kwargs: dict[str, Any] = dict(
            base_url=self._base_url(),
            timeout=self.config.timeout_seconds,
            headers=headers,
        )
        if self.config.proxy_url:
            kwargs["proxy"] = self.config.proxy_url
        return httpx.Client(**kwargs)

    def _request(
        self, client: httpx.Client, method: str, url: str, *, params: JsonDict | None = None
    ) -> httpx.Response:
        """GET/POST con reintentos para fallas transitorias.

        403 y 401 no se reintentan (no son transitorios): se levantan directo. 429 y 5xx
        se reintentan hasta `self.config.max_retries`; agotados los intentos, se levanta
        el error de dominio correspondiente en vez del ultimo raw exception.
        """
        attempts = max(1, self.config.max_retries)
        last_error: Exception | None = None
        for _ in range(attempts):
            try:
                response = client.request(method, url, params=params)
            except httpx.TimeoutException as exc:
                last_error = SourceUnavailable(
                    f"timeout en {url}: {exc}", source_slug=self.source_slug
                )
                continue
            except httpx.TransportError as exc:
                last_error = SourceUnavailable(
                    f"error de conexion en {url}: {exc}", source_slug=self.source_slug
                )
                continue

            if response.status_code == 403:
                raise BlockedBySource(f"403 en {url}", source_slug=self.source_slug)
            if response.status_code == 401:
                raise AuthenticationError(f"401 en {url}", source_slug=self.source_slug)
            if response.status_code == 429:
                last_error = RateLimited(f"429 en {url}", source_slug=self.source_slug)
                continue
            if response.status_code >= 500:
                last_error = SourceUnavailable(
                    f"{response.status_code} en {url}", source_slug=self.source_slug
                )
                continue
            return response

        assert last_error is not None  # pragma: no cover - defensivo
        raise last_error

    # --- search ---------------------------------------------------------------

    def search(self, query: SearchQuery) -> Iterator[RawListing]:
        page_size = min(query.page_size or MAX_SEARCH_PAGE_SIZE, MAX_SEARCH_PAGE_SIZE)
        max_results = query.max_results
        max_pages = self.config.max_pages
        offset = 0
        emitted = 0
        pages_fetched = 0

        with self._client() as client:
            while True:
                if max_pages is not None and pages_fetched >= max_pages:
                    return
                params: JsonDict = {"limit": page_size, "offset": offset}
                if query.term:
                    params["q"] = query.term
                if query.category:
                    params["category"] = query.category
                params.update(query.raw_params)

                response = self._request(
                    client, "GET", f"/sites/{self.config.site_id}/search", params=params
                )
                data = response.json()
                results: list[JsonDict] = data.get("results") or []
                pages_fetched += 1
                if not results:
                    return

                item_ids = [item["id"] for item in results if item.get("id")]
                detail_by_id: dict[str, JsonDict] = {}
                if query.enrich and item_ids:
                    detail_by_id = self._fetch_items_detail(client, item_ids)

                origin = (
                    f"{self._base_url()}/sites/{self.config.site_id}/search"
                    f"?q={query.term or ''}&offset={offset}"
                )
                for item in results:
                    if max_results is not None and emitted >= max_results:
                        return
                    item_id = item.get("id")
                    payload = detail_by_id.get(item_id, item) if item_id else item

                    related: JsonDict = {}
                    if query.enrich:
                        seller_id = (payload.get("seller") or {}).get("id")
                        if seller_id:
                            related["seller"] = self._fetch_seller(client, seller_id)
                        if item_id:
                            related["reviews"] = self._fetch_reviews(client, item_id)

                    yield RawListing(
                        source_slug=self.source_slug,
                        external_id=item_id,
                        payload=payload,
                        related=related,
                        origin_ref=origin,
                    )
                    emitted += 1

                offset += page_size
                total = (data.get("paging") or {}).get("total")
                if total is not None and offset >= total:
                    return

    # --- refresh ----------------------------------------------------------------

    def fetch_by_ids(self, request: RefreshRequest) -> Iterator[RawListing]:
        batch_size = min(request.batch_size or MAX_ITEMS_PER_BATCH, MAX_ITEMS_PER_BATCH)

        with self._client() as client:
            for chunk in _chunk(request.external_ids, batch_size):
                detail_by_id = self._fetch_items_detail(client, chunk)
                for item_id in chunk:
                    payload = detail_by_id.get(item_id)
                    if payload is None:
                        # id no encontrado / publicacion dada de baja: el worker lo cuenta
                        # como "no encontrado", no como error de normalizacion.
                        continue
                    related: JsonDict = {}
                    if request.enrich:
                        seller_id = (payload.get("seller") or {}).get("id")
                        if seller_id:
                            related["seller"] = self._fetch_seller(client, seller_id)
                        related["reviews"] = self._fetch_reviews(client, item_id)
                    yield RawListing(
                        source_slug=self.source_slug,
                        external_id=item_id,
                        payload=payload,
                        related=related,
                        origin_ref=f"{self._base_url()}/items?ids={item_id}",
                    )

    # --- helpers de I/O compartidos ---------------------------------------------

    def _fetch_items_detail(
        self, client: httpx.Client, ids: Iterable[str]
    ) -> dict[str, JsonDict]:
        """`GET /items?ids=...` en lotes de `MAX_ITEMS_PER_BATCH`.

        La respuesta es una lista de `{"code": 200, "body": {...item...}}` (o `code` !=
        200 para un id invalido/dado de baja): se descartan las entradas que no vinieron
        con `code == 200` en vez de propagar el error, para no tirar abajo el lote entero
        por un solo id roto.
        """
        detail: dict[str, JsonDict] = {}
        ids = list(ids)
        for chunk in _chunk(ids, MAX_ITEMS_PER_BATCH):
            response = self._request(
                client, "GET", "/items", params={"ids": ",".join(chunk)}
            )
            payload = response.json()
            entries = payload if isinstance(payload, list) else []
            for entry in entries:
                body = entry.get("body") or {}
                item_id = body.get("id") or entry.get("id")
                if entry.get("code") == 200 and item_id:
                    detail[item_id] = body
        return detail

    def _fetch_seller(self, client: httpx.Client, seller_id: Any) -> JsonDict | None:
        try:
            response = self._request(client, "GET", f"/users/{seller_id}")
        except (AuthenticationError, BlockedBySource, SourceUnavailable, RateLimited):
            # La reputacion del vendedor es un "nice to have" de enrichment: si falla,
            # `normalize()` cae a seller_level=None (desconocido), no aborta el listing.
            return None
        if response.status_code != 200:
            return None
        return response.json()

    def _fetch_reviews(self, client: httpx.Client, item_id: str) -> JsonDict | None:
        try:
            response = self._request(client, "GET", f"/reviews/item/{item_id}")
        except (AuthenticationError, BlockedBySource, SourceUnavailable, RateLimited):
            return None
        if response.status_code != 200:
            # 404 (sin reviews) u otro codigo: "sin reviews", no un error.
            return None
        return response.json()

    # --- normalize (pura) --------------------------------------------------------

    def normalize(self, raw: RawListing) -> NormalizedListingInput:
        item = raw.payload
        external_id = raw.external_id or item.get("id")
        if not external_id:
            raise NormalizationError(
                "item sin id", source_slug=self.source_slug, origin_ref=raw.origin_ref
            )

        title = (item.get("title") or "").strip()
        permalink = item.get("permalink") or f"https://articulo.mercadolibre.com.ar/{external_id}"

        raw_condition = item.get("condition")
        try:
            condition = ItemCondition(raw_condition) if raw_condition else ItemCondition.UNKNOWN
        except ValueError:
            condition = ItemCondition.UNKNOWN

        price = item.get("price")
        if price is None:
            raise NormalizationError(
                f"item {external_id} sin price",
                source_slug=self.source_slug,
                origin_ref=raw.origin_ref,
            )

        shipping = item.get("shipping") or {}
        # Ver punto 4 del docstring del modulo: solo se confirma el caso "envio gratis".
        shipping_cost = Decimal(0) if shipping.get("free_shipping") else None
        fulfillment = self._is_fulfillment(shipping)

        installments = item.get("installments") or {}
        installments_qty = installments.get("quantity")
        installments_amount = installments.get("amount")
        rate = installments.get("rate")
        interest_free = None if rate is None else bool(rate == 0)

        seller = item.get("seller") or {}
        seller_id = seller.get("id")
        seller_name = seller.get("nickname")
        official_store_id = item.get("official_store_id")
        # Aproximacion (punto 3 del docstring): no resolvemos el nombre real de la tienda.
        official_store = seller_name if official_store_id is not None else None

        related_seller = raw.related.get("seller") or {}
        seller_level: str | None = None
        seller_sales: int | None = None
        if related_seller:
            reputation = related_seller.get("seller_reputation") or {}
            power_status = reputation.get("power_seller_status")
            # Ver punto 1 del docstring del modulo: null -> "green" (nivel real conocido),
            # no None (dato faltante) — solo cae a None si no se pudo consultar `/users`.
            seller_level = power_status if power_status in SELLER_LEVELS else "green"
            transactions = reputation.get("transactions") or {}
            seller_sales = transactions.get("total")

        related_reviews = raw.related.get("reviews") or {}
        rating = related_reviews.get("rating_average") if related_reviews else None
        reviews_count = related_reviews.get("total") if related_reviews else None

        attributes = item.get("attributes") or []
        attr_by_id = {
            a.get("id"): a for a in attributes if isinstance(a, dict) and a.get("id")
        }
        warranty_time_attr = (attr_by_id.get("WARRANTY_TIME") or {}).get("value_name")
        warranty_type_attr = (attr_by_id.get("WARRANTY_TYPE") or {}).get("value_name")
        warranty_text = item.get("warranty")
        warranty_months = _parse_warranty_months(warranty_time_attr, warranty_text)
        warranty_type = _parse_warranty_type(warranty_type_attr, warranty_text)
        if warranty_type is WarrantyType.SIN and warranty_months is None:
            warranty_months = 0

        brand = (attr_by_id.get("BRAND") or {}).get("value_name")
        model = (attr_by_id.get("MODEL") or {}).get("value_name")
        gtin = (attr_by_id.get("GTIN") or attr_by_id.get("EAN") or {}).get("value_name")

        product_hint = ProductHint(
            catalog_product_id=item.get("catalog_product_id"),
            gtin=gtin,
            brand=brand,
            model=model,
        )

        try:
            return NormalizedListingInput(
                source_slug=self.source_slug,
                external_id=str(external_id),
                title=title,
                permalink=permalink,
                condition=condition,
                price=_to_decimal(price),
                shipping_cost=shipping_cost,
                currency=item.get("currency_id") or "ARS",
                installments_qty=installments_qty,
                installments_amount=(
                    _to_decimal(installments_amount) if installments_amount is not None else None
                ),
                interest_free=interest_free,
                seller_name=seller_name,
                seller_id=str(seller_id) if seller_id is not None else None,
                seller_level=seller_level,
                seller_sales=seller_sales,
                official_store=official_store,
                fulfillment=fulfillment,
                rating=_to_decimal(rating) if rating is not None else None,
                reviews_count=reviews_count,
                warranty_months=warranty_months,
                warranty_type=warranty_type,
                product_hint=product_hint,
                origin_ref=raw.origin_ref,
            )
        except (ValidationError, InvalidOperation) as exc:
            raise NormalizationError(
                f"no se pudo normalizar {external_id}: {exc}",
                source_slug=self.source_slug,
                origin_ref=raw.origin_ref,
            ) from exc

    @staticmethod
    def _is_fulfillment(shipping: JsonDict) -> bool | None:
        if not shipping:
            return None
        if shipping.get("logistic_type") == "fulfillment":
            return True
        tags = shipping.get("tags") or []
        if "fulfillment" in tags:
            return True
        return False

    # --- salud --------------------------------------------------------------

    def health_check(self) -> HealthStatus:
        start = time.monotonic()
        try:
            with self._client() as client:
                response = client.get(f"/sites/{self.config.site_id}")
        except httpx.TimeoutException as exc:
            return HealthStatus.down(self.source_slug, f"timeout: {exc}")
        except httpx.TransportError as exc:
            return HealthStatus.down(self.source_slug, f"error de conexion: {exc}")

        latency_ms = int((time.monotonic() - start) * 1000)
        if response.status_code == 200:
            return HealthStatus.up(self.source_slug, latency_ms=latency_ms)
        if response.status_code == 403:
            return HealthStatus(
                source_slug=self.source_slug,
                state=HealthState.BLOCKED,
                latency_ms=latency_ms,
                message="403 Forbidden",
            )
        if response.status_code == 429:
            return HealthStatus(
                source_slug=self.source_slug,
                state=HealthState.DEGRADED,
                latency_ms=latency_ms,
                message="429 Too Many Requests",
            )
        return HealthStatus.down(
            self.source_slug, f"status {response.status_code}", latency_ms=latency_ms
        )


def _to_decimal(value: Any) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))

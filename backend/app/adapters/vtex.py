"""Adapter genérico para tiendas sobre VTEX Intelligent Search.

Endpoint:
    GET /api/io/_v/api/intelligent-search/product_search/trade-policy/1
        ?query=TERM&count=COUNT&page=PAGE

Tiendas confirmadas:
    - Cetrogar  (cetrogar.com.ar)
    - Naldo     (naldo.com.ar)

Agregar una tienda nueva = INSERT en `retailer_source` con kind='vtex' y
base_url en config_json. Sin código nuevo.

Campos NO provistos por VTEX IS:
- seller_name: en tiendas propias (1P), el seller es la misma tienda; no se expone en IS.
- seller_level / seller_sales: no hay reputación en IS.
- rating / reviews_count: no expuesto en IS.
- shipping_cost: no expuesto en IS.
- warranty_months / warranty_type: no expuesto en IS.

Precios: ARS enteros (369999 = $ 369.999).
Permalink: {base_url}/{linkText}/p
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from decimal import Decimal, InvalidOperation
from typing import Any, ClassVar

from urllib.parse import quote, urlencode

import httpx
from pydantic import ValidationError

from app.adapters.base import BaseSourceAdapter
from app.adapters.errors import (
    BlockedBySource,
    NormalizationError,
    RateLimited,
    SourceUnavailable,
)
from app.adapters.registry import register_default_for_kind
from app.adapters.types import (
    FetchMode,
    HealthState,
    HealthStatus,
    NormalizedListingInput,
    RefreshRequest,
    ProductHint,
    RawListing,
    SearchQuery,
    SourceCapabilities,
)
from app.enums import ItemCondition, SourceKind, WarrantyType

JsonDict = dict[str, Any]

DEFAULT_BASE_URL = "https://www.cetrogar.com.ar"
DEFAULT_PAGE_SIZE = 48
_IS_PATH = "/api/io/_v/api/intelligent-search/product_search/trade-policy/1"
_LEGACY_PATH = "/api/catalog_system/pub/products/search"

#: Dos sabores de API VTEX conviven en las tiendas argentinas: Intelligent Search
#: (Cetrogar, Naldo) y el Catalog System clásico (Frávega, que devuelve 404 en IS).
#: Se elige por `config_json.api_flavor`; la forma del payload difiere y `normalize`
#: la detecta por presencia de `priceRange` (IS) vs. `items[].sellers[]` (legacy).
FLAVOR_INTELLIGENT_SEARCH = "intelligent_search"
FLAVOR_LEGACY_CATALOG = "legacy_catalog"


def _total_from_resources_header(header: str | None, fallback: int) -> int:
    """`resources: items 0-23/357` -> 357. Sin header, el total es lo que llegó."""
    if not header or "/" not in header:
        return fallback
    try:
        return int(header.rsplit("/", 1)[1])
    except ValueError:
        return fallback


def _first_offer(product: JsonDict) -> JsonDict:
    """`commertialOffer` del primer seller con stock (o del primero, si ninguno informa)."""
    for item in product.get("items") or []:
        sellers = item.get("sellers") or []
        for seller in sellers:
            offer = seller.get("commertialOffer") or {}
            if (offer.get("AvailableQuantity") or 0) > 0:
                return offer
        if sellers:
            return sellers[0].get("commertialOffer") or {}
    return {}


@register_default_for_kind(SourceKind.VTEX)
class VtexAdapter(BaseSourceAdapter):
    """Adapter para tiendas VTEX con Intelligent Search activado."""

    kind: ClassVar[SourceKind] = SourceKind.VTEX
    capabilities: ClassVar[SourceCapabilities] = SourceCapabilities(
        supported_modes=frozenset({FetchMode.SEARCH, FetchMode.REFRESH}),
        supports_incremental=False,
        supports_full_catalog=False,
        provides_seller_reputation=False,
        provides_ratings=False,
        provides_installments=True,
        provides_shipping_cost=False,
        provides_warranty=False,
        provides_catalog_id=False,
    )

    # --- HTTP ---------------------------------------------------------------

    def _base_url(self) -> str:
        return (self.config.base_url or DEFAULT_BASE_URL).rstrip("/")

    def _flavor(self) -> str:
        return getattr(self.config, "api_flavor", None) or FLAVOR_INTELLIGENT_SEARCH

    def _search_path(self) -> str:
        return _LEGACY_PATH if self._flavor() == FLAVOR_LEGACY_CATALOG else _IS_PATH

    def _search_params(self, term: str, page: int, page_size: int) -> dict[str, Any]:
        if self._flavor() == FLAVOR_LEGACY_CATALOG:
            offset = (page - 1) * page_size
            # El Catalog System pagina por rango inclusivo de índices, no por nro. de página.
            params: dict[str, Any] = {"ft": term, "_from": offset, "_to": offset + page_size - 1}
        else:
            params = {"query": term, "count": page_size, "page": page}

        # `search_filters` de `config_json`: parametros extra que acotan la busqueda a
        # una parte del catalogo. Existe para las cadenas de supermercado, donde el
        # rubro que nos interesa es una fraccion minima del total — Jumbo publica
        # 325.794 productos y solo 19.833 son de electro. Sin esto, una ingesta se
        # llevaria el almacen entero a una base de 500 MB.
        # Ejemplo: {"fq": "C:/15/"} (arbol de categorias de VTEX).
        extra = getattr(self.config, "search_filters", None)
        if isinstance(extra, dict):
            params.update(extra)
        return params

    def _client(self) -> httpx.Client:
        headers: dict[str, str] = {
            "Accept": "application/json",
            "User-Agent": (
                self.config.user_agent
                or "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            ),
        }
        headers.update(self.config.headers)
        return httpx.Client(
            base_url=self._base_url(),
            timeout=self.config.timeout_seconds,
            headers=headers,
            **({"proxy": self.config.proxy_url} if self.config.proxy_url else {}),
        )

    def _get(
        self,
        client: httpx.Client,
        params: dict[str, Any] | list[tuple[str, Any]],
        path: str | None = None,
    ) -> JsonDict:
        """GET al endpoint de búsqueda con reintentos para 5xx/429.

        Normaliza ambos sabores a la forma de IS (`{"products": [...],
        "recordsFiltered": N}`): el Catalog System devuelve una lista pelada y el total
        en el header `resources` (`items 0-23/357`).
        """
        attempts = max(1, self.config.max_retries)
        path = path or self._search_path()
        last_error: Exception | None = None
        for _ in range(attempts):
            try:
                # La query se arma a mano para que el espacio viaje como `%20` y no
                # como `+`. httpx usa `+` (codificacion de formulario), y el WAF de
                # Carrefour responde `400 Bad Request! Scripts are not allowed!` a
                # cualquier `ft` que lo contenga — "notebook" pasaba y "smart tv" no.
                # `%20` es valido en todos lados; `+` solo dentro de un form.
                response = client.get(f"{path}?{urlencode(params, quote_via=quote)}")
            except httpx.TimeoutException as exc:
                last_error = SourceUnavailable(
                    f"timeout en IS: {exc}", source_slug=self.source_slug
                )
                continue
            except httpx.TransportError as exc:
                last_error = SourceUnavailable(
                    f"error de conexión: {exc}", source_slug=self.source_slug
                )
                continue

            if response.status_code == 403:
                raise BlockedBySource("403 en IS", source_slug=self.source_slug)
            if response.status_code == 429:
                last_error = RateLimited("429 en IS", source_slug=self.source_slug)
                continue
            if response.status_code >= 500:
                last_error = SourceUnavailable(
                    f"{response.status_code} en IS", source_slug=self.source_slug
                )
                continue

            payload = response.json()
            if isinstance(payload, list):
                return {
                    "products": payload,
                    "recordsFiltered": _total_from_resources_header(
                        response.headers.get("resources"), len(payload)
                    ),
                }
            return payload

        assert last_error is not None
        raise last_error

    # --- search -------------------------------------------------------------

    def search(self, query: SearchQuery) -> Iterator[RawListing]:
        page_size = min(query.page_size or DEFAULT_PAGE_SIZE, DEFAULT_PAGE_SIZE)
        max_results = query.max_results
        max_pages = self.config.max_pages
        page = 1
        emitted = 0
        pages_fetched = 0

        with self._client() as client:
            while True:
                if max_pages is not None and pages_fetched >= max_pages:
                    return

                params = self._search_params(query.term or "", page, page_size)
                params.update(query.raw_params)

                data = self._get(client, params)
                products: list[JsonDict] = data.get("products") or []
                total: int = data.get("recordsFiltered") or 0
                pages_fetched += 1

                if not products:
                    return

                origin = (
                    f"{self._base_url()}{self._search_path()}"
                    f"?q={query.term or ''}&page={page}"
                )
                for product in products:
                    if max_results is not None and emitted >= max_results:
                        return
                    yield RawListing(
                        source_slug=self.source_slug,
                        external_id=str(product.get("productId", "")),
                        payload=product,
                        origin_ref=origin,
                    )
                    emitted += 1

                if page * page_size >= total:
                    return
                page += 1

    # --- refresh ------------------------------------------------------------

    #: Cuantos productos se piden por request. VTEX devuelve como maximo 50 items por
    #: pagina en el Catalog System, asi que pedir mas seria perder los del final.
    _REFRESH_BATCH = 50

    def fetch_by_ids(self, request: RefreshRequest) -> Iterator[RawListing]:
        """Relee publicaciones que ya estan en la base, por `productId`.

        Es el modo que alimenta `price_history`: sin el, cada publicacion tiene un solo
        punto —el del dia que la trajo una busqueda— y no hay contra que comparar para
        saber si una oferta bajo de verdad.

        Se usa **siempre el catalogo legacy**, aunque la tienda este configurada con
        Intelligent Search: el filtro `fq=productId:N` es del Catalog System y funciona en
        las dos (verificado contra Cetrogar, que corre con IS). IS no tiene un equivalente
        para pedir por id.

        Los ids se piden de a `_REFRESH_BATCH` repitiendo `fq`, que es como VTEX expresa
        un OR. Un id que ya no existe simplemente no vuelve en la respuesta, y esa
        publicacion se queda con su ultimo precio conocido — que es el comportamiento
        correcto: que una tienda deje de publicar algo no es informacion de precio.
        """
        ids = [i for i in request.external_ids if i]
        if not ids:
            return

        with self._client() as client:
            for inicio in range(0, len(ids), self._REFRESH_BATCH):
                lote = ids[inicio : inicio + self._REFRESH_BATCH]
                params: list[tuple[str, Any]] = [("fq", f"productId:{pid}") for pid in lote]
                params += [("_from", 0), ("_to", len(lote) - 1)]

                data = self._get(client, params, path=_LEGACY_PATH)
                productos: list[JsonDict] = data.get("products") or []

                origin = f"{self._base_url()}{_LEGACY_PATH}?fq=productId:{lote[0]}&+{len(lote) - 1}"
                for producto in productos:
                    yield RawListing(
                        source_slug=self.source_slug,
                        external_id=str(producto.get("productId", "")),
                        payload=producto,
                        origin_ref=origin,
                    )

    # --- normalize (pura) ---------------------------------------------------

    def normalize(self, raw: RawListing) -> NormalizedListingInput:
        p = raw.payload
        external_id = raw.external_id or str(p.get("productId", ""))
        if not external_id:
            raise NormalizationError(
                "item sin productId", source_slug=self.source_slug, origin_ref=raw.origin_ref
            )

        title = (p.get("productName") or "").strip()
        if not title:
            raise NormalizationError(
                f"item {external_id} sin productName",
                source_slug=self.source_slug,
                origin_ref=raw.origin_ref,
            )

        link_text = p.get("linkText") or external_id
        permalink = f"{self._base_url()}/{link_text}/p"

        offer = _first_offer(p)

        # Precio: gana la oferta del seller, no el `priceRange` que arma Intelligent
        # Search. Los dos coinciden en la mayoria de las tiendas, pero cuando difieren
        # el bueno es el del seller: `priceRange` es un agregado que NO aplica las
        # reglas de precio del vendedor.
        #
        # Verificado el 2026-08-20 con una heladera Drean HDR280F50B: Easy devolvia
        # `priceRange` 734.995 y oferta 661.495, y su propia ficha declara
        # `product:price:amount = 661495.5` en el Open Graph — o sea, el precio que ve
        # quien entra es el del seller. Con el agregado, Easy aparecia $73.500 mas cara
        # de lo que esta y no podia ganar una comparacion nunca.
        #
        # `Price` en 0 significa "sin oferta activa" (seller sin stock), no gratis: en
        # ese caso se cae al agregado, que sigue siendo un precio real de la ficha.
        raw_price = offer.get("Price") or None
        if raw_price is None:
            raw_price = ((p.get("priceRange") or {}).get("sellingPrice") or {}).get("lowPrice")
        if raw_price is None:
            raise NormalizationError(
                f"item {external_id} sin sellingPrice",
                source_slug=self.source_slug,
                origin_ref=raw.origin_ref,
            )

        brand_name = (p.get("brand") or None) or None

        # installments: primer item, primer seller, la opción sin interés con más cuotas
        installments_qty: int | None = None
        installments_amount: Decimal | None = None
        interest_free: bool | None = None
        raw_installments: list[JsonDict] = offer.get("Installments") or []
        free = [i for i in raw_installments if i.get("InterestRate") == 0]
        if free:
            best = max(free, key=lambda i: i.get("NumberOfInstallments", 0))
            installments_qty = best.get("NumberOfInstallments")
            installments_amount = (
                Decimal(str(best["Value"])) if best.get("Value") is not None else None
            )
            interest_free = True

        try:
            return NormalizedListingInput(
                source_slug=self.source_slug,
                external_id=external_id,
                title=title,
                permalink=permalink,
                condition=ItemCondition.UNKNOWN,
                price=Decimal(str(raw_price)),
                shipping_cost=None,
                currency="ARS",
                installments_qty=installments_qty,
                installments_amount=installments_amount,
                interest_free=interest_free,
                seller_name=None,
                seller_id=None,
                seller_level=None,
                seller_sales=None,
                official_store=None,
                fulfillment=None,
                rating=None,
                reviews_count=None,
                warranty_months=None,
                warranty_type=WarrantyType.UNKNOWN,
                product_hint=ProductHint(brand=brand_name),
                origin_ref=raw.origin_ref,
            )
        except (ValidationError, InvalidOperation) as exc:
            raise NormalizationError(
                f"no se pudo normalizar {external_id}: {exc}",
                source_slug=self.source_slug,
                origin_ref=raw.origin_ref,
            ) from exc

    # --- salud --------------------------------------------------------------

    def health_check(self) -> HealthStatus:
        start = time.monotonic()
        try:
            with self._client() as client:
                data = self._get(client, self._search_params("test", 1, 1))
        except BlockedBySource as exc:
            return HealthStatus(
                source_slug=self.source_slug,
                state=HealthState.BLOCKED,
                message=str(exc),
            )
        except SourceUnavailable as exc:
            return HealthStatus.down(self.source_slug, str(exc))
        except RateLimited as exc:
            return HealthStatus(
                source_slug=self.source_slug,
                state=HealthState.DEGRADED,
                message=str(exc),
            )
        except Exception as exc:
            return HealthStatus.down(self.source_slug, f"error inesperado: {exc}")

        latency_ms = int((time.monotonic() - start) * 1000)
        if data.get("products") is not None:
            return HealthStatus.up(self.source_slug, latency_ms=latency_ms)
        return HealthStatus.down(
            self.source_slug, "respuesta IS sin campo 'products'", latency_ms=latency_ms
        )

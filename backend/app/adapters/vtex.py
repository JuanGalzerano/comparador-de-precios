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


@register_default_for_kind(SourceKind.VTEX)
class VtexAdapter(BaseSourceAdapter):
    """Adapter para tiendas VTEX con Intelligent Search activado."""

    kind: ClassVar[SourceKind] = SourceKind.VTEX
    capabilities: ClassVar[SourceCapabilities] = SourceCapabilities(
        supported_modes=frozenset({FetchMode.SEARCH}),
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

    def _get(self, client: httpx.Client, params: dict[str, Any]) -> JsonDict:
        """GET al endpoint IS con reintentos para 5xx/429."""
        attempts = max(1, self.config.max_retries)
        last_error: Exception | None = None
        for _ in range(attempts):
            try:
                response = client.get(_IS_PATH, params=params)
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

            return response.json()

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

                params: dict[str, Any] = {
                    "query": query.term or "",
                    "count": page_size,
                    "page": page,
                }
                params.update(query.raw_params)

                data = self._get(client, params)
                products: list[JsonDict] = data.get("products") or []
                total: int = data.get("recordsFiltered") or 0
                pages_fetched += 1

                if not products:
                    return

                origin = f"{self._base_url()}{_IS_PATH}?query={query.term or ''}&page={page}"
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

        price_range = p.get("priceRange") or {}
        selling = price_range.get("sellingPrice") or {}
        raw_price = selling.get("lowPrice")
        if raw_price is None:
            raise NormalizationError(
                f"item {external_id} sin sellingPrice",
                source_slug=self.source_slug,
                origin_ref=raw.origin_ref,
            )

        brand_name = (p.get("brand") or None) or None

        # installments: primer item, primer seller, primera opción sin interés con más cuotas
        installments_qty: int | None = None
        installments_amount: Decimal | None = None
        interest_free: bool | None = None
        items = p.get("items") or []
        if items:
            sellers = (items[0].get("sellers") or [])
            if sellers:
                offer = sellers[0].get("commertialOffer") or {}
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
                data = self._get(client, {"query": "test", "count": 1, "page": 1})
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

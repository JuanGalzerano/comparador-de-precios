"""Adapter de Frávega (GraphQL propio sobre Next.js).

Endpoint descubierto por inspección del Apollo state de la SPA:

    POST https://www.fravega.com/api/v2    (GraphQL, sin autenticación)

Query usada:
    items(filters: { keywords }, pagination: { size, from }) {
        total
        results {
            code
            item { title slug brand { name } }
            pricing { salePrice listPrice discount }
            seller { commercialName }
        }
    }

Campos que esta fuente NO provee (se dejan en None, no se inventan):
- seller_level / seller_sales: Frávega no expone reputación de vendedor en la búsqueda.
- rating / reviews_count: no hay endpoint de reseñas en la API descubierta.
- installments_qty / installments_amount: el campo `installments` del schema es
  una lista de Collections (badges), no cuotas — se omite.
- shipping_cost: no expuesto en la búsqueda.
- warranty_months / warranty_type: no expuesto en la búsqueda.

Precios: `salePrice` y `listPrice` son ARS enteros (e.g. 1_399_999 = $ 1.399.999).
Permalink: `https://www.fravega.com/p/{slug}-{code}/` (ver `_permalink`).
"""

from __future__ import annotations

import re
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
from app.enums import ItemCondition, SourceKind, WarrantyType

JsonDict = dict[str, Any]

DEFAULT_BASE_URL = "https://www.fravega.com"
DEFAULT_PAGE_SIZE = 48  # igual al que usa la UI de Frávega


_GQL_SEARCH = """
query CotejoSearch($filters: Filters, $pagination: Pagination) {
  items(filters: $filters, pagination: $pagination) {
    total
    results {
      code
      item {
        title
        slug
        brand { name }
      }
      pricing {
        salePrice
        listPrice
        discount
      }
      seller {
        commercialName
      }
    }
  }
}
"""


@register_adapter("fravega")
class FravegaAdapter(BaseSourceAdapter):
    """Adapter del GraphQL interno de Frávega (Apollo/Next.js, no VTEX estándar).

    Registrado por slug `fravega`; para tiendas VTEX estándar usar `VtexAdapter`.
    """

    kind: ClassVar[SourceKind] = SourceKind.VTEX
    capabilities: ClassVar[SourceCapabilities] = SourceCapabilities(
        supported_modes=frozenset({FetchMode.SEARCH}),
        supports_incremental=False,
        supports_full_catalog=False,
        provides_seller_reputation=False,
        provides_ratings=False,
        provides_installments=False,
        provides_shipping_cost=False,
        provides_warranty=False,
        provides_catalog_id=False,
    )

    # --- HTTP ---------------------------------------------------------------

    def _base_url(self) -> str:
        return (self.config.base_url or DEFAULT_BASE_URL).rstrip("/")

    def _client(self) -> httpx.Client:
        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        headers.update(self.config.headers)
        if self.config.user_agent:
            headers["User-Agent"] = self.config.user_agent
        return httpx.Client(
            base_url=self._base_url(),
            timeout=self.config.timeout_seconds,
            headers=headers,
            **({"proxy": self.config.proxy_url} if self.config.proxy_url else {}),
        )

    def _gql(
        self, client: httpx.Client, variables: JsonDict
    ) -> JsonDict:
        """POST al endpoint GraphQL con reintentos para 5xx/429."""
        attempts = max(1, self.config.max_retries)
        last_error: Exception | None = None
        for _ in range(attempts):
            try:
                response = client.post(
                    "/api/v2",
                    json={"query": _GQL_SEARCH, "variables": variables},
                )
            except httpx.TimeoutException as exc:
                last_error = SourceUnavailable(
                    f"timeout en GraphQL: {exc}", source_slug=self.source_slug
                )
                continue
            except httpx.TransportError as exc:
                last_error = SourceUnavailable(
                    f"error de conexión: {exc}", source_slug=self.source_slug
                )
                continue

            if response.status_code == 403:
                raise BlockedBySource("403 en /api/v2", source_slug=self.source_slug)
            if response.status_code == 429:
                last_error = RateLimited("429 en /api/v2", source_slug=self.source_slug)
                continue
            if response.status_code >= 500:
                last_error = SourceUnavailable(
                    f"{response.status_code} en /api/v2", source_slug=self.source_slug
                )
                continue

            payload = response.json()
            if errors := payload.get("errors"):
                msg = "; ".join(e.get("message", str(e)) for e in errors)
                raise SourceUnavailable(
                    f"GraphQL error: {msg}", source_slug=self.source_slug
                )
            return payload.get("data", {})

        assert last_error is not None
        raise last_error

    # --- search -------------------------------------------------------------

    def search(self, query: SearchQuery) -> Iterator[RawListing]:
        page_size = min(query.page_size or DEFAULT_PAGE_SIZE, DEFAULT_PAGE_SIZE)
        max_results = query.max_results
        max_pages = self.config.max_pages
        offset = 0
        emitted = 0
        pages_fetched = 0

        with self._client() as client:
            while True:
                if max_pages is not None and pages_fetched >= max_pages:
                    return

                variables: JsonDict = {
                    "filters": {"keywords": query.term or ""},
                    "pagination": {"size": page_size, "from": offset},
                }
                variables["filters"].update(query.raw_params)

                data = self._gql(client, variables)
                items_data = data.get("items") or {}
                results: list[JsonDict] = items_data.get("results") or []
                total: int = items_data.get("total") or 0
                pages_fetched += 1

                if not results:
                    return

                origin = (
                    f"{self._base_url()}/api/v2"
                    f"?keywords={query.term or ''}&from={offset}"
                )
                for item in results:
                    if max_results is not None and emitted >= max_results:
                        return
                    yield RawListing(
                        source_slug=self.source_slug,
                        external_id=str(item.get("code", "")),
                        payload=item,
                        origin_ref=origin,
                    )
                    emitted += 1

                offset += page_size
                if offset >= total:
                    return

    # --- normalize (pura) ---------------------------------------------------

    def _permalink(self, slug: str, code: str) -> str:
        """URL pública del producto: `{base}/p/{slug}-{code}/`.

        Verificado contra los links que el propio buscador de Frávega genera. El formato
        `/producto/{slug}/{code}/` que se usaba antes devolvía 200 pero renderizaba la
        página de resultados de búsqueda, no el producto.

        El slug que devuelve la API puede traer comillas tipográficas y otros caracteres
        no-ASCII (`notebook-hp-15-6”-amd-...`); Frávega sirve la misma página con el slug
        limpio, así que se normalizan a guiones en vez de percent-encodearlos.
        """
        cleaned = re.sub(r"[^a-z0-9]+", "-", slug.lower()).strip("-")
        return f"{self._base_url()}/p/{cleaned}-{code}/"

    def normalize(self, raw: RawListing) -> NormalizedListingInput:
        item = raw.payload
        external_id = raw.external_id or str(item.get("code", ""))
        if not external_id:
            raise NormalizationError(
                "item sin code", source_slug=self.source_slug, origin_ref=raw.origin_ref
            )

        inner = item.get("item") or {}
        title = (inner.get("title") or "").strip()
        if not title:
            raise NormalizationError(
                f"item {external_id} sin title",
                source_slug=self.source_slug,
                origin_ref=raw.origin_ref,
            )

        permalink = self._permalink(inner.get("slug") or external_id, external_id)

        pricing = item.get("pricing") or {}
        raw_price = pricing.get("salePrice")
        if raw_price is None:
            raise NormalizationError(
                f"item {external_id} sin salePrice",
                source_slug=self.source_slug,
                origin_ref=raw.origin_ref,
            )

        seller = item.get("seller") or {}
        seller_name = seller.get("commercialName") or None

        brand_name = (inner.get("brand") or {}).get("name") or None

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
                installments_qty=None,
                installments_amount=None,
                interest_free=None,
                seller_name=seller_name,
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
                data = self._gql(
                    client,
                    {"filters": {"keywords": "test"}, "pagination": {"size": 1, "from": 0}},
                )
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
        if data.get("items") is not None:
            return HealthStatus.up(self.source_slug, latency_ms=latency_ms)
        return HealthStatus.down(
            self.source_slug, "respuesta GraphQL sin campo 'items'", latency_ms=latency_ms
        )

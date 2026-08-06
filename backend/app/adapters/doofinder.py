"""Adapter para tiendas que usan Doofinder como buscador (Megatone y otras).

Doofinder es un buscador SaaS que muchas tiendas contratan en vez de usar el de su
plataforma. El sitio consulta el índice desde el navegador del visitante, así que el
endpoint y el `hashid` del índice son públicos por diseño — es el mismo canal que usa la
tienda para su propio buscador, no un scraping del HTML.

Endpoint:
    GET https://{zone}-search.doofinder.com/6/{hashid}/_search?query=TERM&rpp=N&page=P

Configuración en `retailer_source.config_json`:
    {"base_url": "https://www.megatone.net", "hashid": "7d78...", "zone": "us1"}

El `hashid` de una tienda sale de su script de configuración:
    https://{zone}-config.doofinder.com/2.x/{installation-id}.js

Campos que esta fuente SÍ provee y que VTEX no:
- `gtin`: código del producto en la tienda. Se guarda como `catalog_product_id`, que
  habilita la vía determinística del matcher entre publicaciones de la misma tienda.
- `categories` / `category_path`: categoría real, útil para navegación por rubro.
- `free_shipping` y cuotas, en texto libre ("20 x $96060 Sin Interés").

Campos que NO provee (se dejan en None, no se inventan):
- reputación del vendedor, reseñas, garantía, costo de envío cuando no es gratis.
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

DEFAULT_ZONE = "us1"
DEFAULT_PAGE_SIZE = 48

#: "20 x $96060 Sin Interés" -> (20, 96060, sin interés)
_INSTALLMENTS_RE = re.compile(
    r"(\d+)\s*x\s*\$?\s*([\d.,]+)\s*(sin inter[eé]s)?", re.IGNORECASE
)


#: Se registra por slug, no como default del `kind`: `SCRAPER` está reservado para un
#: spider propio, que es otra cosa. Agregar una tienda Doofinder = sumar su slug acá y
#: un INSERT en `retailer_source` con su `hashid`.
@register_adapter("megatone")
class DoofinderAdapter(BaseSourceAdapter):
    """Adapter del índice de búsqueda de Doofinder de una tienda."""

    kind: ClassVar[SourceKind] = SourceKind.SCRAPER
    capabilities: ClassVar[SourceCapabilities] = SourceCapabilities(
        supported_modes=frozenset({FetchMode.SEARCH}),
        supports_incremental=False,
        supports_full_catalog=False,
        provides_seller_reputation=False,
        provides_ratings=False,
        provides_installments=True,
        provides_shipping_cost=False,
        provides_warranty=False,
        provides_catalog_id=True,
    )

    # --- HTTP ---------------------------------------------------------------

    def _base_url(self) -> str:
        return (self.config.base_url or "").rstrip("/")

    def _hashid(self) -> str:
        hashid = getattr(self.config, "hashid", None)
        if not hashid:
            raise SourceUnavailable(
                "falta `hashid` en config_json (ver docstring del adapter)",
                source_slug=self.source_slug,
            )
        return str(hashid)

    def _zone(self) -> str:
        return str(getattr(self.config, "zone", None) or DEFAULT_ZONE)

    def _search_url(self) -> str:
        return f"https://{self._zone()}-search.doofinder.com/6/{self._hashid()}/_search"

    def _client(self) -> httpx.Client:
        headers: dict[str, str] = {
            "Accept": "application/json",
            "User-Agent": (
                self.config.user_agent
                or "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            ),
        }
        # Doofinder valida el origen contra el dominio dado de alta en el índice.
        if self._base_url():
            headers["Origin"] = self._base_url()
            headers["Referer"] = f"{self._base_url()}/"
        headers.update(self.config.headers)
        return httpx.Client(
            timeout=self.config.timeout_seconds,
            headers=headers,
            **({"proxy": self.config.proxy_url} if self.config.proxy_url else {}),
        )

    def _get(self, client: httpx.Client, params: dict[str, Any]) -> JsonDict:
        attempts = max(1, self.config.max_retries)
        last_error: Exception | None = None
        for _ in range(attempts):
            try:
                response = client.get(self._search_url(), params=params)
            except httpx.TimeoutException as exc:
                last_error = SourceUnavailable(f"timeout: {exc}", source_slug=self.source_slug)
                continue
            except httpx.TransportError as exc:
                last_error = SourceUnavailable(
                    f"error de conexión: {exc}", source_slug=self.source_slug
                )
                continue

            if response.status_code in (401, 403):
                raise BlockedBySource(
                    f"{response.status_code} en Doofinder", source_slug=self.source_slug
                )
            if response.status_code == 429:
                last_error = RateLimited("429 en Doofinder", source_slug=self.source_slug)
                continue
            if response.status_code >= 500:
                last_error = SourceUnavailable(
                    f"{response.status_code} en Doofinder", source_slug=self.source_slug
                )
                continue
            return response.json()

        assert last_error is not None
        raise last_error

    # --- search -------------------------------------------------------------

    def search(self, query: SearchQuery) -> Iterator[RawListing]:
        page_size = min(query.page_size or DEFAULT_PAGE_SIZE, 100)
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
                    "rpp": page_size,
                    "page": page,
                }
                params.update(query.raw_params)

                data = self._get(client, params)
                results: list[JsonDict] = data.get("results") or []
                total: int = data.get("total") or 0
                pages_fetched += 1

                if not results:
                    return

                origin = f"{self._search_url()}?query={query.term or ''}&page={page}"
                for item in results:
                    if max_results is not None and emitted >= max_results:
                        return
                    external_id = str(item.get("gtin") or item.get("dfid") or "")
                    yield RawListing(
                        source_slug=self.source_slug,
                        external_id=external_id,
                        payload=item,
                        origin_ref=origin,
                    )
                    emitted += 1

                if page * page_size >= total:
                    return
                page += 1

    # --- normalize (pura) ---------------------------------------------------

    def _parse_installments(self, text: str | None) -> tuple[int | None, Decimal | None, bool | None]:
        if not text:
            return None, None, None
        match = _INSTALLMENTS_RE.search(text)
        if not match:
            return None, None, None
        qty = int(match.group(1))
        raw_amount = match.group(2).replace(".", "").replace(",", ".")
        try:
            amount = Decimal(raw_amount)
        except InvalidOperation:
            return qty, None, bool(match.group(3))
        return qty, amount, bool(match.group(3))

    def normalize(self, raw: RawListing) -> NormalizedListingInput:
        item = raw.payload
        external_id = raw.external_id or str(item.get("gtin") or "")
        if not external_id:
            raise NormalizationError(
                "item sin gtin ni dfid", source_slug=self.source_slug, origin_ref=raw.origin_ref
            )

        title = (item.get("title") or "").strip()
        if not title:
            raise NormalizationError(
                f"item {external_id} sin title",
                source_slug=self.source_slug,
                origin_ref=raw.origin_ref,
            )

        raw_price = item.get("price")
        if raw_price is None:
            raise NormalizationError(
                f"item {external_id} sin price",
                source_slug=self.source_slug,
                origin_ref=raw.origin_ref,
            )

        permalink = item.get("link") or self._base_url()
        free_shipping = str(item.get("free_shipping") or "").lower() == "true"
        qty, amount, interest_free = self._parse_installments(item.get("highlight_installments"))

        # `categories` trae la ruta completa en mayúsculas y algunas etiquetas internas
        # ("M_HP", "S_TECNOMUNDO"); `category_path` es la legible ("Informática | Notebooks").
        category_path = item.get("category_path") or ""
        category = category_path.split("|")[-1].strip() or None

        try:
            return NormalizedListingInput(
                source_slug=self.source_slug,
                external_id=external_id,
                title=title,
                permalink=permalink,
                condition=ItemCondition.NEW,
                price=Decimal(str(raw_price)),
                # Solo se completa cuando es gratis: el costo real depende del código
                # postal del comprador y no viaja en el índice.
                shipping_cost=Decimal(0) if free_shipping else None,
                currency="ARS",
                installments_qty=qty,
                installments_amount=amount,
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
                product_hint=ProductHint(
                    catalog_product_id=external_id,
                    category=category,
                ),
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
                data = self._get(client, {"query": "test", "rpp": 1, "page": 1})
        except BlockedBySource as exc:
            return HealthStatus(
                source_slug=self.source_slug, state=HealthState.BLOCKED, message=str(exc)
            )
        except SourceUnavailable as exc:
            return HealthStatus.down(self.source_slug, str(exc))
        except RateLimited as exc:
            return HealthStatus(
                source_slug=self.source_slug, state=HealthState.DEGRADED, message=str(exc)
            )
        except Exception as exc:
            return HealthStatus.down(self.source_slug, f"error inesperado: {exc}")

        latency_ms = int((time.monotonic() - start) * 1000)
        if data.get("results") is not None:
            return HealthStatus.up(self.source_slug, latency_ms=latency_ms)
        return HealthStatus.down(
            self.source_slug, "respuesta sin campo 'results'", latency_ms=latency_ms
        )

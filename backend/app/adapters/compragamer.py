"""Adapter de Compra Gamer (catálogo completo publicado como archivo JSON).

A diferencia del resto de las fuentes, Compra Gamer no expone un endpoint de búsqueda:
publica **el catálogo entero** en archivos estáticos que su propio frontend descarga y
filtra en el navegador. O sea que la búsqueda ocurre del lado del cliente, y este adapter
hace exactamente lo mismo: baja el catálogo una vez y filtra en memoria.

    https://static.compragamer.com/productos        catálogo (~1.350 productos, ~9 MB)
    https://static.compragamer.com/marcas           marcas + garantía por marca
    https://static.compragamer.com/categorias_sub   subcategorías

Los tres se cachean por instancia del adapter: una corrida de ingesta con varios términos
descarga el catálogo una sola vez.

**Precios: pesos enteros.** `precioEspecial` es el precio que muestra la tienda
(`2882400` = $ 2.882.400) y `precioLista` es el precio tachado. Verificado contra la
ficha pública del producto 18434 el 2026-08-06; hay un test que lo fija, porque una
fuente que publicara en centavos o en miles ensuciaría todas las comparaciones sin que
se note a simple vista.

**Limitación conocida — el precio destacado ya trae descuento por medio de pago.**
Compra Gamer muestra como "Mejor precio" el que incluye 10% off por transferencia
bancaria; con tarjeta el producto sale `precioLista`. Las otras fuentes publican su
precio de lista sin descuentos de este tipo, así que Compra Gamer aparece más barata de
lo que sale pagando con tarjeta.

Se guarda igual `precioEspecial` — decisión explícita — porque es el precio que el
usuario ve al hacer clic, y mostrar otro número generaría desconfianza en el
comparador. La solución de fondo es guardar los dos y mostrar "$X con transferencia /
$Y con tarjeta"; necesita una columna nueva en `listing` y está anotada en
`PENDIENTE.md`. Vale para cualquier fuente que en el futuro exponga precios por medio
de pago: el retail argentino los usa mucho.

Campos que esta fuente SÍ provee y las otras no:
- **Garantía real**, derivada de la marca (`garantia_meses_por_defecto`), y si es
  garantía oficial del fabricante o del comercio.
- Categoría propia y stock.

Campos que NO provee: reputación del vendedor, reseñas, costo de envío.
"""

from __future__ import annotations

import re
import time
import unicodedata
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
    RefreshRequest,
    SearchQuery,
    SourceCapabilities,
)
from app.enums import ItemCondition, SourceKind, WarrantyType

JsonDict = dict[str, Any]

DEFAULT_BASE_URL = "https://compragamer.com"
DEFAULT_STATIC_URL = "https://static.compragamer.com"

#: El catálogo son ~9 MB: no entra en el timeout por defecto de una búsqueda.
CATALOG_TIMEOUT = 90.0


def _fold(text: str) -> str:
    """minúsculas y sin acentos, para comparar términos contra títulos."""
    lowered = text.lower()
    return "".join(
        c for c in unicodedata.normalize("NFD", lowered) if unicodedata.category(c) != "Mn"
    )


@register_adapter("compragamer")
class CompraGamerAdapter(BaseSourceAdapter):
    """Adapter del catálogo estático de Compra Gamer."""

    kind: ClassVar[SourceKind] = SourceKind.SCRAPER
    capabilities: ClassVar[SourceCapabilities] = SourceCapabilities(
        supported_modes=frozenset({FetchMode.SEARCH, FetchMode.REFRESH}),
        supports_incremental=False,
        # El catálogo completo se baja SIEMPRE, así que una búsqueda sin término
        # devuelve todo: esta fuente sí soporta el barrido entero.
        supports_full_catalog=True,
        provides_seller_reputation=False,
        provides_ratings=False,
        provides_installments=False,
        provides_shipping_cost=False,
        provides_warranty=True,
        provides_catalog_id=True,
    )

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._catalog: list[JsonDict] | None = None
        self._brands: dict[int, JsonDict] = {}
        self._categories: dict[int, str] = {}

    # --- HTTP ---------------------------------------------------------------

    def _base_url(self) -> str:
        return (self.config.base_url or DEFAULT_BASE_URL).rstrip("/")

    def _static_url(self) -> str:
        return str(getattr(self.config, "static_url", None) or DEFAULT_STATIC_URL).rstrip("/")

    def _client(self) -> httpx.Client:
        headers: dict[str, str] = {
            "Accept": "application/json",
            "Origin": self._base_url(),
            "Referer": f"{self._base_url()}/",
            "User-Agent": (
                self.config.user_agent
                or "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            ),
        }
        headers.update(self.config.headers)
        return httpx.Client(
            base_url=self._static_url(),
            timeout=CATALOG_TIMEOUT,
            headers=headers,
            **({"proxy": self.config.proxy_url} if self.config.proxy_url else {}),
        )

    def _fetch(self, client: httpx.Client, path: str) -> Any:
        attempts = max(1, self.config.max_retries)
        last_error: Exception | None = None
        for _ in range(attempts):
            try:
                response = client.get(path)
            except httpx.TimeoutException as exc:
                last_error = SourceUnavailable(f"timeout en {path}: {exc}", source_slug=self.source_slug)
                continue
            except httpx.TransportError as exc:
                last_error = SourceUnavailable(
                    f"error de conexión en {path}: {exc}", source_slug=self.source_slug
                )
                continue

            if response.status_code == 403:
                raise BlockedBySource(f"403 en {path}", source_slug=self.source_slug)
            if response.status_code == 429:
                last_error = RateLimited(f"429 en {path}", source_slug=self.source_slug)
                continue
            if response.status_code >= 500:
                last_error = SourceUnavailable(
                    f"{response.status_code} en {path}", source_slug=self.source_slug
                )
                continue
            return response.json()

        assert last_error is not None
        raise last_error

    @staticmethod
    def _as_list(payload: Any) -> list[JsonDict]:
        """Los archivos devuelven una lista, o un objeto que la envuelve."""
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            for value in payload.values():
                if isinstance(value, list):
                    return value
        return []

    def _load(self, client: httpx.Client) -> list[JsonDict]:
        if self._catalog is not None:
            return self._catalog

        self._catalog = self._as_list(self._fetch(client, "/productos"))
        self._brands = {
            int(b["id"]): b for b in self._as_list(self._fetch(client, "/marcas")) if "id" in b
        }
        self._categories = {
            int(c["id"]): str(c.get("nombre") or "").strip()
            for c in self._as_list(self._fetch(client, "/categorias_sub"))
            if "id" in c
        }
        return self._catalog

    # --- search -------------------------------------------------------------

    @staticmethod
    def _matches(term: str, name: str) -> bool:
        """Todas las palabras del término tienen que aparecer en el nombre.

        Es la misma lógica de un buscador simple, y alcanza porque el filtrado es local:
        no hay costo de red por término.
        """
        folded = _fold(name)
        return all(word in folded for word in _fold(term).split())

    def search(self, query: SearchQuery) -> Iterator[RawListing]:
        max_results = query.max_results
        emitted = 0

        with self._client() as client:
            catalog = self._load(client)

        term = (query.term or "").strip()
        origin = f"{self._static_url()}/productos?q={term}"

        for item in catalog:
            if max_results is not None and emitted >= max_results:
                return
            name = str(item.get("nombre") or "")
            if not name:
                continue
            if term and not self._matches(term, name):
                continue
            # Sin stock no es una oferta real: la publicación existe pero no se puede
            # comprar, así que entraría a la comparación con un precio que no está vivo.
            if not item.get("stock") or not item.get("vendible"):
                continue

            yield RawListing(
                source_slug=self.source_slug,
                external_id=str(item.get("id_producto") or ""),
                payload=item,
                origin_ref=origin,
            )
            emitted += 1

    def fetch_by_ids(self, request: RefreshRequest) -> Iterator[RawListing]:
        """Relee publicaciones ya conocidas, por `id_producto`.

        Es gratis en esta fuente: el adapter se baja el catálogo entero igual (una sola
        request a `/productos`), así que refrescar es filtrar en memoria lo ya descargado.

        A diferencia de `search`, acá **no** se filtra por stock. En una búsqueda, una
        publicación sin stock no es una oferta real y no debería entrar. Pero en un
        refresh la publicación ya está en la base: si dejara de emitirla, su precio se
        congelaría en el último valor conocido sin que nadie se entere. Emitirla deja que
        el precio del día quede registrado en el historial.
        """
        buscados = {str(i) for i in request.external_ids if i}
        if not buscados:
            return

        with self._client() as client:
            catalog = self._load(client)

        origin = f"{self._static_url()}/productos?refresh={len(buscados)}"
        for item in catalog:
            product_id = str(item.get("id_producto") or "")
            if product_id in buscados:
                yield RawListing(
                    source_slug=self.source_slug,
                    external_id=product_id,
                    payload=item,
                    origin_ref=origin,
                )

    # --- normalize (pura) ---------------------------------------------------

    def _permalink(self, name: str, product_id: str) -> str:
        """`/producto/{Nombre_Con_Guiones_Bajos}_{id}`, el formato del propio sitio."""
        slug = re.sub(r"[^A-Za-z0-9]+", "_", _fold(name)).strip("_")
        return f"{self._base_url()}/producto/{slug}_{product_id}"

    def normalize(self, raw: RawListing) -> NormalizedListingInput:
        item = raw.payload
        external_id = raw.external_id or str(item.get("id_producto") or "")
        if not external_id:
            raise NormalizationError(
                "item sin id_producto", source_slug=self.source_slug, origin_ref=raw.origin_ref
            )

        title = str(item.get("nombre") or "").strip()
        if not title:
            raise NormalizationError(
                f"item {external_id} sin nombre",
                source_slug=self.source_slug,
                origin_ref=raw.origin_ref,
            )

        # `precioEspecial` es el precio que muestra la tienda; `precioLista` es el
        # tachado. Ver el docstring del módulo: la escala es pesos enteros.
        raw_price = item.get("precioEspecial") or item.get("precioLista")
        if not raw_price:
            raise NormalizationError(
                f"item {external_id} sin precio",
                source_slug=self.source_slug,
                origin_ref=raw.origin_ref,
            )

        brand_row = self._brands.get(int(item.get("id_marca") or -1)) or {}
        brand = str(brand_row.get("marca_nombre_alias") or brand_row.get("nombre") or "").strip()
        if brand.lower() in {"", "sin definir"}:
            brand = ""

        category = self._categories.get(int(item.get("id_subcategoria") or -1)) or None

        # La garantía viene por MARCA, no por producto: es la política del comercio.
        warranty_months = brand_row.get("garantia_meses_por_defecto")
        warranty_type = WarrantyType.UNKNOWN
        if warranty_months:
            warranty_type = (
                WarrantyType.OFICIAL if brand_row.get("garantia_oficial") else WarrantyType.VENDEDOR
            )
        else:
            warranty_months = None

        try:
            return NormalizedListingInput(
                source_slug=self.source_slug,
                external_id=external_id,
                title=title,
                permalink=self._permalink(title, external_id),
                condition=ItemCondition.NEW,
                price=Decimal(str(raw_price)),
                shipping_cost=None,
                currency="ARS",
                installments_qty=None,
                installments_amount=None,
                interest_free=None,
                seller_name=None,
                seller_id=None,
                seller_level=None,
                seller_sales=None,
                official_store=None,
                fulfillment=None,
                rating=None,
                reviews_count=None,
                warranty_months=warranty_months,
                warranty_type=warranty_type,
                product_hint=ProductHint(
                    catalog_product_id=external_id,
                    brand=brand or None,
                    category=category,
                ),
                origin_ref=raw.origin_ref,
            )
        except (ValidationError, InvalidOperation, TypeError) as exc:
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
                catalog = self._as_list(self._fetch(client, "/productos"))
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
        if catalog:
            return HealthStatus.up(self.source_slug, latency_ms=latency_ms)
        return HealthStatus.down(self.source_slug, "catálogo vacío", latency_ms=latency_ms)

"""Adapters de fuentes de datos.

`base.py` define el contrato (`SourceAdapter`), `types.py` los DTOs, `errors.py` la
taxonomia de fallas y `registry.py` el mapeo fila-de-config -> clase.

Implementaciones concretas (`MercadoLibreAdapter`, `VtexAdapter`, `PreciosClarosAdapter`,
spiders de Scrapy) son tareas aparte y se registran con `@register_adapter(...)`.
"""

from app.adapters.base import BaseSourceAdapter, SourceAdapter
from app.adapters.errors import (
    AdapterError,
    AuthenticationError,
    BlockedBySource,
    NormalizationError,
    RateLimited,
    SourceUnavailable,
    UnsupportedFetchMode,
)
from app.adapters.doofinder import DoofinderAdapter
from app.adapters.fravega import FravegaAdapter
from app.adapters.mercadolibre import MercadoLibreAdapter
from app.adapters.vtex import VtexAdapter
from app.adapters.registry import (
    AdapterNotFound,
    build_adapter,
    register_adapter,
    register_default_for_kind,
)
from app.adapters.types import (
    AdapterConfig,
    BatchRequest,
    FetchMode,
    FetchRequest,
    HealthState,
    HealthStatus,
    NormalizedListingInput,
    ProductHint,
    RawFormat,
    RawListing,
    RefreshRequest,
    SearchQuery,
    SourceCapabilities,
)

__all__ = [
    "AdapterConfig",
    "AdapterError",
    "AdapterNotFound",
    "AuthenticationError",
    "BaseSourceAdapter",
    "BatchRequest",
    "BlockedBySource",
    "FetchMode",
    "FetchRequest",
    "HealthState",
    "HealthStatus",
    "DoofinderAdapter",
    "FravegaAdapter",
    "MercadoLibreAdapter",
    "VtexAdapter",
    "NormalizationError",
    "NormalizedListingInput",
    "ProductHint",
    "RateLimited",
    "RawFormat",
    "RawListing",
    "RefreshRequest",
    "SearchQuery",
    "SourceAdapter",
    "SourceCapabilities",
    "SourceUnavailable",
    "UnsupportedFetchMode",
    "build_adapter",
    "register_adapter",
    "register_default_for_kind",
]

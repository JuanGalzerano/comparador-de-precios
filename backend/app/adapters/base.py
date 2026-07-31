"""El contrato `SourceAdapter`: la unica cosa que el worker de ingesta conoce.

Un solo worker itera `retailer_source` con `status='active'`, construye el adapter que
corresponda (ver `app/adapters/registry.py`) y hace siempre lo mismo:

    for raw in adapter.fetch_listings(request):
        normalized = adapter.normalize(raw)
        upsert(normalized)

Todo lo especifico de la fuente (auth, paginacion, ZIPs, rate limit, selectores CSS) queda
adentro del adapter.


Desviaciones respecto del boceto del plan, y por que
----------------------------------------------------

1. `fetch_listings(self, query: SearchQuery)` -> `fetch_listings(self, request: FetchRequest)`.

   `SearchQuery` no le entra a dos de las cuatro fuentes previstas. Precios Claros/SEPA es
   un ZIP diario completo: no tiene termino de busqueda, tiene fecha de snapshot y
   particiones. Y el refresco de precios que alimenta `price_history` no es una busqueda
   tampoco: es "releeme estos 400 external_id que ya tengo", que en ML es un endpoint
   distinto (`/items?ids=`) y en un scraper es la URL de cada ficha, no la de busqueda.

   Se evaluaron tres formas:
   (a) agregar un segundo metodo `fetch_batch()` al Protocol -> obliga a todo adapter a
       implementar (o stubear) un metodo que no le aplica, y el worker termina con un `if`
       por tipo de fuente, que es justo lo que la interfaz venia a evitar;
   (b) `SearchQuery` con todos los campos opcionales y semantica implicita -> un
       `SearchQuery` con `term=None` y `snapshot_date` puesto no significa nada claro, y
       nada valida que la combinacion tenga sentido;
   (c) union discriminada por `mode` (elegida) -> un solo metodo, cada modo con sus campos
       obligatorios validados por pydantic, y el adapter declara en
       `capabilities.supported_modes` que sabe atender. El worker chequea la capacidad
       antes de despachar; pedir un modo no soportado es `UnsupportedFetchMode`.

   Costo aceptado: el adapter hace un dispatch por `mode`. `BaseSourceAdapter` lo escribe
   una sola vez para que ningun adapter concreto repita ese `if`.

2. `kind: Literal["api", "vtex", "sepa_feed", "scraper"]` -> `kind: SourceKind`.

   Mismos cuatro valores, pero es el ENUM que ya usa la columna `retailer_source.kind`.
   Un `Literal` duplicado se desincroniza el dia que se agregue un tipo de fuente.

3. Se agrega `capabilities: SourceCapabilities` como tercer atributo de clase.

   Sin esto el worker no puede saber si una fuente soporta un modo (ver punto 1) y el
   scoring no puede distinguir "esta fuente no informa reputacion" de "este vendedor no
   tiene reputacion", que son cosas muy distintas para el usuario.

4. Se publica el Protocol (contrato estructural, para tipar) Y una ABC
   `BaseSourceAdapter` (implementacion comun, opcional).

   El Protocol es lo que pide el plan y es lo correcto para el worker: permite conformar
   sin heredar, que importa para el `ScrapyAdapter`, donde la clase util suele ser un
   `Spider` de Scrapy que ya hereda de otra cosa. La ABC existe para que los adapters que
   SI pueden heredar no repitan config, dispatch y guardas.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable, Iterator
from typing import ClassVar, Protocol, runtime_checkable

from app.adapters.errors import UnsupportedFetchMode
from app.adapters.types import (
    AdapterConfig,
    BatchRequest,
    FetchRequest,
    HealthState,
    HealthStatus,
    NormalizedListingInput,
    RawListing,
    RefreshRequest,
    SearchQuery,
    SourceCapabilities,
)
from app.enums import SourceKind

__all__ = [
    "SourceAdapter",
    "BaseSourceAdapter",
]


@runtime_checkable
class SourceAdapter(Protocol):
    """Lo que tiene que cumplir cualquier fuente de datos de Cotejo."""

    #: Igual a `retailer_source.slug`. Es el vinculo entre codigo y fila de config.
    source_slug: str
    kind: SourceKind
    capabilities: SourceCapabilities

    def fetch_listings(self, request: FetchRequest) -> Iterable[RawListing]:
        """Trae registros crudos de la fuente.

        Devuelve `Iterable` y no `list` a proposito: se espera un generador. Un volcado
        de SEPA son decenas de miles de registros y no tienen que entrar todos en memoria;
        el worker consume de a uno y hace upsert incremental, asi una corrida interrumpida
        deja igual todo lo que alcanzo a procesar.

        Paginacion, reintentos y rate-limit son responsabilidad del adapter: para el worker
        esto es una sola secuencia.

        Levanta: `UnsupportedFetchMode`, `SourceUnavailable`, `RateLimited`,
        `AuthenticationError`, `BlockedBySource`.
        """
        ...

    def normalize(self, raw: RawListing) -> NormalizedListingInput:
        """Convierte un registro crudo al shape de `listing`.

        Tiene que ser una funcion PURA: sin I/O, sin acceso a la base. Todo lo que necesite
        (reputacion del vendedor, reviews) ya tiene que venir en `RawListing.related`,
        puesto por `fetch_listings`. Eso permite re-normalizar registros historicos cuando
        se corrige un parser, sin volver a pegarle a la fuente, y testear con fixtures.

        Levanta `NormalizationError` si el registro no es recuperable.
        """
        ...

    def health_check(self) -> HealthStatus:
        """Sonda barata de disponibilidad, sin efectos sobre los datos.

        La corre el panel admin y el worker antes de una corrida grande. No levanta
        excepciones: los fallos se reportan como `HealthState.DOWN` / `BLOCKED`.
        """
        ...


class BaseSourceAdapter(ABC):
    """Implementacion comun opcional del Protocol.

    Aporta: binding de `retailer_source.config_json` a un `AdapterConfig` tipado, el
    dispatch por `mode` con su guarda de capacidades, y un `health_check` por defecto.
    Un adapter concreto implementa solo los modos que su fuente soporta:

        class MercadoLibreAdapter(BaseSourceAdapter):
            kind = SourceKind.API
            capabilities = SourceCapabilities(
                supported_modes=frozenset({FetchMode.SEARCH, FetchMode.REFRESH}), ...
            )
            def search(self, query): ...
            def fetch_by_ids(self, request): ...
            def normalize(self, raw): ...
    """

    #: Subclases sobreescriben con su `AdapterConfig` especifico.
    config_model: ClassVar[type[AdapterConfig]] = AdapterConfig

    kind: ClassVar[SourceKind]
    capabilities: ClassVar[SourceCapabilities] = SourceCapabilities()

    def __init__(self, source_slug: str, config: AdapterConfig | dict | None = None) -> None:
        self.source_slug = source_slug
        if config is None:
            config = {}
        self.config = (
            config
            if isinstance(config, self.config_model)
            else self.config_model.model_validate(
                config.model_dump() if isinstance(config, AdapterConfig) else config
            )
        )

    # --- Entrada unica -----------------------------------------------------

    def fetch_listings(self, request: FetchRequest) -> Iterator[RawListing]:
        """Valida la capacidad y despacha al metodo del modo correspondiente."""
        mode = request.mode
        if not self.capabilities.supports(mode):
            raise UnsupportedFetchMode(
                f"la fuente no soporta el modo '{mode.value}' "
                f"(soporta: {sorted(m.value for m in self.capabilities.supported_modes)})",
                source_slug=self.source_slug,
            )
        if isinstance(request, SearchQuery):
            return iter(self.search(request))
        if isinstance(request, BatchRequest):
            return iter(self.fetch_batch(request))
        if isinstance(request, RefreshRequest):
            return iter(self.fetch_by_ids(request))
        raise UnsupportedFetchMode(  # pragma: no cover - defensivo
            f"tipo de request desconocido: {type(request).__name__}",
            source_slug=self.source_slug,
        )

    # --- Un metodo por modo; se implementa solo lo que la fuente soporta ----

    def search(self, query: SearchQuery) -> Iterable[RawListing]:
        raise UnsupportedFetchMode("search no implementado", source_slug=self.source_slug)

    def fetch_batch(self, request: BatchRequest) -> Iterable[RawListing]:
        raise UnsupportedFetchMode("batch no implementado", source_slug=self.source_slug)

    def fetch_by_ids(self, request: RefreshRequest) -> Iterable[RawListing]:
        raise UnsupportedFetchMode("refresh no implementado", source_slug=self.source_slug)

    # --- Obligatorio -------------------------------------------------------

    @abstractmethod
    def normalize(self, raw: RawListing) -> NormalizedListingInput:
        """Ver `SourceAdapter.normalize`."""

    # --- Opcional ----------------------------------------------------------

    def health_check(self) -> HealthStatus:
        """Por defecto: `UNKNOWN`. Cada adapter deberia sondear su fuente de verdad."""
        return HealthStatus(
            source_slug=self.source_slug,
            state=HealthState.UNKNOWN,
            message="el adapter no implementa health_check",
        )

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<{type(self).__name__} slug={self.source_slug!r} kind={self.kind}>"

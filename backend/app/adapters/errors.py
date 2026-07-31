"""Errores del contrato de adapters.

El worker de ingesta distingue por tipo para decidir que hacer: reintentar con backoff,
esperar `retry_after`, o apagar la fuente y escalar a una persona. Todo lo que sale de un
adapter deberia ser una de estas (envolver `requests`/`httpx`/parsers), asi
`retailer_source.last_error` guarda algo accionable y no un traceback de libreria.
"""

from __future__ import annotations


class AdapterError(Exception):
    """Base de todos los errores de adapter."""

    #: Si tiene sentido que el worker lo reintente solo.
    retryable: bool = False

    def __init__(self, message: str, *, source_slug: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.source_slug = source_slug

    def __str__(self) -> str:
        prefix = f"[{self.source_slug}] " if self.source_slug else ""
        return f"{prefix}{self.message}"


class SourceUnavailable(AdapterError):
    """La fuente no respondio o devolvio 5xx. Reintentable."""

    retryable = True


class RateLimited(AdapterError):
    """La fuente devolvio 429. Reintentable respetando `retry_after`."""

    retryable = True

    def __init__(
        self,
        message: str,
        *,
        source_slug: str | None = None,
        retry_after_seconds: float | None = None,
    ) -> None:
        super().__init__(message, source_slug=source_slug)
        self.retry_after_seconds = retry_after_seconds


class AuthenticationError(AdapterError):
    """Credenciales invalidas o vencidas. No reintentar: hay que arreglar la config."""


class BlockedBySource(AdapterError):
    """403 / captcha / anti-bot.

    Deliberadamente NO reintentable: insistir es exactamente lo que convierte un problema
    tecnico en un problema de ToS. El worker pasa la fuente a
    `SourceStatus.BLOCKED_TOS_REVIEW` y espera decision humana.
    """


class UnsupportedFetchMode(AdapterError):
    """Se le pidio a un adapter un modo que no declara en `capabilities.supported_modes`.

    Es un bug de orquestacion (p.ej. mandarle una `SearchQuery` a Precios Claros), no una
    falla de la fuente.
    """


class NormalizationError(AdapterError):
    """El raw no se pudo convertir a `NormalizedListingInput`.

    Afecta a un registro, no a la corrida: el worker deberia contarlo, loguear
    `origin_ref` y seguir con el siguiente.
    """

    def __init__(
        self,
        message: str,
        *,
        source_slug: str | None = None,
        origin_ref: str | None = None,
    ) -> None:
        super().__init__(message, source_slug=source_slug)
        self.origin_ref = origin_ref

"""Registro de adapters: de una fila de `retailer_source` al objeto que la atiende.

La resolucion es por slug primero y por `kind` despues, porque hay dos casos distintos:

- `MercadoLibreAdapter` sirve exactamente a una fuente -> se registra por slug.
- `VtexAdapter` es parametrizable y sirve a N retailers (`fravega`, `cetrogar`, ...) que
  solo difieren en `config_json` -> se registra como default del kind `vtex`, y agregar un
  retailer VTEX nuevo pasa a ser un INSERT, sin codigo nuevo.

Todavia no hay adapters registrados: `MercadoLibreAdapter` es la proxima tarea.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable, TypeVar

from app.adapters.base import SourceAdapter
from app.enums import SourceKind

if TYPE_CHECKING:
    from app.models.retailer_source import RetailerSource

A = TypeVar("A", bound=type)

_BY_SLUG: dict[str, type] = {}
_BY_KIND: dict[SourceKind, type] = {}


class AdapterNotFound(LookupError):
    """No hay adapter para esa fuente. Es un error de configuracion, no de datos."""


def register_adapter(*slugs: str) -> Callable[[A], A]:
    """Registra una clase de adapter para uno o mas `retailer_source.slug`."""

    def decorator(cls: A) -> A:
        for slug in slugs:
            _BY_SLUG[slug] = cls
        return cls

    return decorator


def register_default_for_kind(kind: SourceKind) -> Callable[[A], A]:
    """Registra una clase como fallback para todas las fuentes de un `kind`."""

    def decorator(cls: A) -> A:
        _BY_KIND[kind] = cls
        return cls

    return decorator


def resolve_adapter_class(slug: str, kind: SourceKind) -> type:
    cls = _BY_SLUG.get(slug) or _BY_KIND.get(kind)
    if cls is None:
        raise AdapterNotFound(
            f"no hay adapter registrado para slug={slug!r} ni para kind={kind.value!r}"
        )
    return cls


def build_adapter(source: "RetailerSource") -> SourceAdapter:
    """Instancia el adapter de una fila de `retailer_source` con su `config_json`.

    Es el unico punto donde el worker de ingesta toca el ORM para armar un adapter; de ahi
    en adelante trabaja solo contra el Protocol.
    """
    cls = resolve_adapter_class(source.slug, source.kind)
    return cls(source_slug=source.slug, config=source.config_json or {})


def registered_slugs() -> tuple[str, ...]:
    return tuple(sorted(_BY_SLUG))


def registered_kinds() -> tuple[SourceKind, ...]:
    return tuple(_BY_KIND)

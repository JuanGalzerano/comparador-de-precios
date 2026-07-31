"""Port de `scoreOf()` a Python.

Fuente de verdad (no reinventar la formula, es un PORT):
`project/Cotejo - Comparador.dc.html:561-571`

```js
scoreOf(l, min, max) {
  const final = l.price + l.ship;
  const priceScore = max === min ? 1 : 1 - (final - min) / (max - min);
  const repScore = { platinum: 1, gold: 0.78, silver: 0.5, green: 0.3 }[l.level] ?? 0.3;
  const ratingScore = l.reviews === 0 ? 0.35 : (l.rating / 5) * Math.min(1, 0.55 + Math.log10(l.reviews + 1) / 4);
  const warrScore = Math.min(1, l.warranty / 12) * (l.wType === 'oficial' ? 1 : l.wType === 'vendedor' ? 0.8 : 0);
  const perkScore = (l.full ? 0.5 : 0) + (l.ship === 0 ? 0.3 : 0) + (l.free ? 0.2 : 0);
  const w = { price: this.props.pesoPrecio ?? 0.34, rep: 0.2, rating: 0.18, warranty: this.props.pesoGarantia ?? 0.2, perks: 0.08 };
  const t = w.price + w.rep + w.rating + w.warranty + w.perks;
  return Math.round(((priceScore * w.price + repScore * w.rep + ratingScore * w.rating + warrScore * w.warranty + perkScore * w.perks) / t) * 100);
}
```

Mapeo de campos del mock a `NormalizedListingInput` (ver docstring de esa clase en
`app/adapters/types.py`):

    l.price + l.ship  -> listing.final_price (`price + coalesce(shipping_cost, 0)`)
    l.level           -> listing.seller_level      (`app.enums.SELLER_LEVELS`)
    l.rating          -> listing.rating
    l.reviews         -> listing.reviews_count
    l.warranty        -> listing.warranty_months
    l.wType           -> listing.warranty_type     (`app.enums.WarrantyType`)
    l.full            -> listing.fulfillment
    l.ship === 0       -> listing.shipping_cost == 0
    l.free            -> listing.interest_free

Sobre `l.free`: en el mock NO es el flag de filtro de UI `filters.free` (ese es un toggle
de busqueda, ver linea 494/593 del `.dc.html`). Es una propiedad de cada listing, y su
unico uso fuera de `scoreOf()` es `instNote: l.instQ > 1 ? (l.free ? 'sin interes' : 'con
interes') : ...` (lineas 640/662) — es literalmente "cuotas sin interes", que ya tiene
columna dedicada en el schema (`listing.interest_free`, comentada en el modelo como
"`l.free` (cuotas sin interes)"). No hay nada que adivinar aca: el campo ya existe.

Por que `min`/`max` y los pesos son PARAMETROS y no se calculan solos aca
--------------------------------------------------------------------------
`scoreOf()` normaliza el eje precio contra el rango del set que el usuario esta viendo
en ese momento (post-filtros), no contra "todo el catalogo" ni contra un valor fijo. Ese
set lo arma el endpoint de busqueda/producto (ver TODO en `app/api/routers/search.py`),
no esta funcion: `score_of()` se mantiene pura y testeable con cualquier min/max, y
`score_listings()` es el atajo para el caso comun (calcular min/max sobre el mismo set que
se va a puntuar).

Rounding: `Math.round` de JS redondea .5 siempre hacia +Infinity (nunca "banker's
rounding"). El `round()` de Python usa round-half-to-even, que puede diferir en un punto
exacto de .5. Para que el port sea fiel bit a bit se usa `_js_round`.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from decimal import Decimal
from typing import NamedTuple

from app.adapters.types import NormalizedListingInput
from app.enums import WarrantyType

__all__ = [
    "DEFAULT_PESO_GARANTIA",
    "DEFAULT_PESO_PRECIO",
    "final_price_bounds",
    "score_listings",
    "score_of",
]

#: `w.rep`, `w.rating`, `w.perks` en el JS: no son configurables ahi (no salen de
#: `this.props`), asi que tampoco lo son aca.
_PESO_REPUTACION = 0.20
_PESO_RATING = 0.18
_PESO_PERKS = 0.08

#: `this.props.pesoPrecio ?? 0.34` / `this.props.pesoGarantia ?? 0.20`: estos si son
#: configurables en el JS (props del componente), por eso quedan como default de argumento.
DEFAULT_PESO_PRECIO = 0.34
DEFAULT_PESO_GARANTIA = 0.20

#: `{ platinum: 1, gold: 0.78, silver: 0.5, green: 0.3 }[l.level] ?? 0.3`
_REPUTATION_SCORES: dict[str, float] = {
    "platinum": 1.0,
    "gold": 0.78,
    "silver": 0.5,
    "green": 0.3,
}
_REPUTATION_FALLBACK = 0.3

#: `l.wType === 'oficial' ? 1 : l.wType === 'vendedor' ? 0.8 : 0`
_WARRANTY_MULTIPLIER: dict[WarrantyType, float] = {
    WarrantyType.OFICIAL: 1.0,
    WarrantyType.VENDEDOR: 0.8,
    WarrantyType.SIN: 0.0,
    WarrantyType.UNKNOWN: 0.0,
}


def _js_round(value: float) -> int:
    """`Math.round` de JS: redondea .5 hacia +Infinity, no al par mas cercano."""
    return math.floor(value + 0.5)


class PriceBounds(NamedTuple):
    """`min`/`max` de `final_price` sobre un set de publicaciones."""

    min_final_price: Decimal
    max_final_price: Decimal


def final_price_bounds(listings: Sequence[NormalizedListingInput]) -> PriceBounds:
    """Calcula `min`/`max` de `final_price` sobre el mismo set que se va a puntuar.

    `scoreOf()` en el mock recibe `min`/`max` ya calculados por el caller (`render()`
    los saca de `Math.min(...)`/`Math.max(...)` sobre las publicaciones visibles); esto
    es el equivalente, para no repetir el `min()`/`max()` en cada endpoint.

    Levanta `ValueError` si `listings` esta vacio: no hay min/max que calcular, y
    devolver un default silencioso (0/0, o el propio listing) esconde un bug de
    orquestacion (llamar a esto con el set vacio) en vez de fallar temprano.
    """
    if not listings:
        raise ValueError("final_price_bounds() necesita al menos una publicacion")
    finals = [item.final_price for item in listings]
    return PriceBounds(min(finals), max(finals))


def score_of(
    listing: NormalizedListingInput,
    *,
    min_final_price: Decimal | float | int,
    max_final_price: Decimal | float | int,
    peso_precio: float = DEFAULT_PESO_PRECIO,
    peso_garantia: float = DEFAULT_PESO_GARANTIA,
) -> int:
    """Port directo de `scoreOf()`. Mismo input -> mismo score (entero 0-100).

    Args:
        listing: la publicacion a puntuar.
        min_final_price, max_final_price: rango de `final_price` del set VISIBLE que se
            esta comparando (no de todo el catalogo). Verlos como los `min`/`max` que el
            JS recibe ya calculados por `render()`. Se acepta `Decimal`/`float`/`int`
            para no forzar al caller a convertir; interna mente se opera en `float`,
            igual que JS (todos los numeros ahi son IEEE-754 double).
        peso_precio, peso_garantia: equivalentes a `this.props.pesoPrecio` /
            `this.props.pesoGarantia` en el componente (unicos pesos configurables).

    El resto de los pesos (`rep`, `rating`, `perks`) son fijos en el JS, y por eso
    tambien lo son aca.
    """
    final = float(listing.final_price)
    lo = float(min_final_price)
    hi = float(max_final_price)
    price_score = 1.0 if hi == lo else 1.0 - (final - lo) / (hi - lo)

    rep_score = _REPUTATION_SCORES.get(listing.seller_level or "", _REPUTATION_FALLBACK)

    reviews = listing.reviews_count or 0
    if reviews == 0:
        rating_score = 0.35
    else:
        rating = float(listing.rating or 0)
        rating_score = (rating / 5.0) * min(1.0, 0.55 + math.log10(reviews + 1) / 4.0)

    warranty_months = listing.warranty_months or 0
    warr_multiplier = _WARRANTY_MULTIPLIER.get(listing.warranty_type, 0.0)
    warr_score = min(1.0, warranty_months / 12.0) * warr_multiplier

    perk_score = (
        (0.5 if listing.fulfillment else 0.0)
        + (0.3 if listing.shipping_cost is not None and listing.shipping_cost == 0 else 0.0)
        + (0.2 if listing.interest_free else 0.0)
    )

    w_price = peso_precio
    w_rep = _PESO_REPUTACION
    w_rating = _PESO_RATING
    w_warranty = peso_garantia
    w_perks = _PESO_PERKS
    total_weight = w_price + w_rep + w_rating + w_warranty + w_perks

    weighted = (
        price_score * w_price
        + rep_score * w_rep
        + rating_score * w_rating
        + warr_score * w_warranty
        + perk_score * w_perks
    )
    return _js_round((weighted / total_weight) * 100)


def score_listings(
    listings: Sequence[NormalizedListingInput],
    *,
    peso_precio: float = DEFAULT_PESO_PRECIO,
    peso_garantia: float = DEFAULT_PESO_GARANTIA,
) -> list[int]:
    """`score_of()` para cada publicacion del set, normalizando contra el propio set.

    Atajo para el caso comun de los endpoints (`/search`, `/producto/:id`): puntuar TODO
    un cluster de publicaciones a la vez contra su propio rango de precio final. Si se
    necesita puntuar contra un rango distinto (p.ej. un listing nuevo contra un set ya
    calculado), usar `score_of()` directamente con el `min`/`max` que corresponda.
    """
    if not listings:
        return []
    bounds = final_price_bounds(listings)
    return [
        score_of(
            item,
            min_final_price=bounds.min_final_price,
            max_final_price=bounds.max_final_price,
            peso_precio=peso_precio,
            peso_garantia=peso_garantia,
        )
        for item in listings
    ]

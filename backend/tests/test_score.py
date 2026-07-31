"""Tests del port de `scoreOf()` (`app/scoring/score.py`).

La formula de referencia usada para calcular los valores esperados es una
transcripcion independiente de `project/Cotejo - Comparador.dc.html:561-571`
(no importa nada de `app.scoring.score`): sirve para detectar errores de copia en el
port. El caso de MLA-8821 esta ademas verificado a mano (ver comentario en su test).
"""

from __future__ import annotations

import math
from decimal import Decimal

import pytest

from app.adapters.types import NormalizedListingInput
from app.enums import WarrantyType
from app.scoring.score import (
    DEFAULT_PESO_GARANTIA,
    DEFAULT_PESO_PRECIO,
    final_price_bounds,
    score_listings,
    score_of,
)

_WARRANTY_JS_VALUE = {
    WarrantyType.OFICIAL: "oficial",
    WarrantyType.VENDEDOR: "vendedor",
    WarrantyType.SIN: "sin",
    WarrantyType.UNKNOWN: "unknown",
}


def _reference_score(
    listing: NormalizedListingInput,
    min_final_price,
    max_final_price,
    *,
    peso_precio: float = DEFAULT_PESO_PRECIO,
    peso_garantia: float = DEFAULT_PESO_GARANTIA,
) -> int:
    """Reimplementacion directa del JS, independiente de `score_of()`."""
    final = float(listing.final_price)
    lo, hi = float(min_final_price), float(max_final_price)
    price_score = 1.0 if hi == lo else 1 - (final - lo) / (hi - lo)

    rep_score = {"platinum": 1, "gold": 0.78, "silver": 0.5, "green": 0.3}.get(
        listing.seller_level, 0.3
    )

    reviews = listing.reviews_count or 0
    if reviews == 0:
        rating_score = 0.35
    else:
        rating_score = (float(listing.rating) / 5) * min(
            1, 0.55 + math.log10(reviews + 1) / 4
        )

    warranty = listing.warranty_months or 0
    wtype = _WARRANTY_JS_VALUE[listing.warranty_type]
    wtype_mult = 1 if wtype == "oficial" else 0.8 if wtype == "vendedor" else 0
    warr_score = min(1, warranty / 12) * wtype_mult

    perk_score = (
        (0.5 if listing.fulfillment else 0)
        + (0.3 if listing.shipping_cost == 0 else 0)
        + (0.2 if listing.interest_free else 0)
    )

    w_price, w_rep, w_rating, w_warranty, w_perks = (
        peso_precio,
        0.2,
        0.18,
        peso_garantia,
        0.08,
    )
    total = w_price + w_rep + w_rating + w_warranty + w_perks
    raw = (
        price_score * w_price
        + rep_score * w_rep
        + rating_score * w_rating
        + warr_score * w_warranty
        + perk_score * w_perks
    ) / total * 100
    return math.floor(raw + 0.5)


def _listing(**overrides) -> NormalizedListingInput:
    data = dict(
        source_slug="mercadolibre",
        external_id="MLA-TEST",
        title="Producto de prueba",
        permalink="https://articulo.mercadolibre.com.ar/MLA-TEST",
        price=Decimal("1000"),
        shipping_cost=Decimal("0"),
        seller_level="green",
        rating=Decimal("4.5"),
        reviews_count=100,
        warranty_months=12,
        warranty_type=WarrantyType.OFICIAL,
        fulfillment=False,
        interest_free=False,
    )
    data.update(overrides)
    return NormalizedListingInput(**data)


# ---------------------------------------------------------------------------
# Tabla de reputacion: platinum/gold/silver/green + fallback desconocido
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "seller_level",
    ["platinum", "gold", "silver", "green", "unranked", None],
)
def test_reputation_table(seller_level):
    listing = _listing(seller_level=seller_level, price=Decimal("500"))
    expected = _reference_score(listing, min_final_price=100, max_final_price=1000)
    assert score_of(listing, min_final_price=100, max_final_price=1000) == expected


def test_reputation_unknown_level_falls_back_to_030():
    # Un nivel que no esta en la tabla (o None) cae al mismo default que el JS: `?? 0.3`.
    known_green = _listing(seller_level="green")
    unknown = _listing(seller_level="algo-que-ml-no-manda")
    assert score_of(known_green, min_final_price=0, max_final_price=1000) == score_of(
        unknown, min_final_price=0, max_final_price=1000
    )


# ---------------------------------------------------------------------------
# Caso 0 reviews: ratingScore = 0.35 fijo, sin importar `rating`
# ---------------------------------------------------------------------------


def test_zero_reviews_is_fixed_rating_score():
    listing = _listing(reviews_count=0, rating=None)
    expected = _reference_score(listing, min_final_price=0, max_final_price=2000)
    got = score_of(listing, min_final_price=0, max_final_price=2000)
    assert got == expected

    # Con 0 reviews, aunque `rating` fuera muy alto no deberia importar (ratingScore fijo
    # en 0.35): dos listings que solo difieren en `rating` con reviews_count=0 empatan.
    same_but_no_rating = _listing(reviews_count=0, rating=Decimal("5"))
    assert score_of(listing, min_final_price=0, max_final_price=2000) == score_of(
        same_but_no_rating, min_final_price=0, max_final_price=2000
    )


# ---------------------------------------------------------------------------
# Caso min == max: priceScore = 1 (no ZeroDivisionError)
# ---------------------------------------------------------------------------


def test_min_equals_max_gives_perfect_price_score():
    listing = _listing(price=Decimal("777"), shipping_cost=Decimal("0"))
    expected = _reference_score(listing, min_final_price=777, max_final_price=777)
    got = score_of(listing, min_final_price=777, max_final_price=777)
    assert got == expected
    # priceScore=1 con los pesos default: si ademas rep/rating/warranty/perks son maximos,
    # el score deberia acercarse a 100.
    perfect = _listing(
        price=Decimal("777"),
        shipping_cost=Decimal("0"),
        seller_level="platinum",
        rating=Decimal("5"),
        reviews_count=10_000,
        warranty_months=12,
        warranty_type=WarrantyType.OFICIAL,
        fulfillment=True,
        interest_free=True,
    )
    assert score_of(perfect, min_final_price=777, max_final_price=777) == 100


# ---------------------------------------------------------------------------
# Caso realista, verificado a mano contra `catalog().iphone` del mock
# (project/Cotejo - Comparador.dc.html:513-522)
# ---------------------------------------------------------------------------


def test_full_listing_matches_hand_verified_mock_score():
    # MLA-8821 tal cual el catalogo del mock:
    # L('MLA-8821', 'MacStation', 'iPhone 13 128GB Midnight — sellado',
    #   1049000, 0, true, 12, 87416, true, 'platinum', 48200,
    #   'Apple Premium Reseller', 4.9, 1840, 12, 'oficial', 'new')
    listing = _listing(
        external_id="MLA-8821",
        title="iPhone 13 128GB Midnight — sellado",
        permalink="https://articulo.mercadolibre.com.ar/MLA-8821",
        price=Decimal("1049000"),
        shipping_cost=Decimal("0"),
        fulfillment=True,
        interest_free=True,
        seller_level="platinum",
        official_store="Apple Premium Reseller",
        rating=Decimal("4.9"),
        reviews_count=1840,
        warranty_months=12,
        warranty_type=WarrantyType.OFICIAL,
    )
    # min/max de `final` sobre las 10 publicaciones del cluster `iphone` del mock:
    #   min = 702000 (MLA-1904: 690000 + 12000)
    #   max = 1112000 (MLA-6631: 1112000 + 0)
    min_final_price = Decimal("702000")
    max_final_price = Decimal("1112000")

    # A mano:
    #   priceScore = 1 - (1049000-702000)/(1112000-702000) = 1 - 347000/410000 = 0.15365853...
    #   repScore   = 1 (platinum)
    #   ratingScore= (4.9/5) * min(1, 0.55 + log10(1841)/4) = 0.98 * 1 = 0.98
    #   warrScore  = min(1, 12/12) * 1 = 1
    #   perkScore  = 0.5 (full) + 0.3 (ship 0) + 0.2 (free) = 1.0
    #   pesos default: price .34 rep .2 rating .18 warranty .2 perks .08 (t = 1.0)
    #   raw = .15365853*.34 + 1*.2 + .98*.18 + 1*.2 + 1*.08
    #       = 0.05224390 + 0.2 + 0.1764 + 0.2 + 0.08 = 0.70864390
    #   *100 = 70.86439... -> Math.round -> 71
    assert score_of(
        listing, min_final_price=min_final_price, max_final_price=max_final_price
    ) == 71
    assert (
        _reference_score(
            listing, min_final_price=min_final_price, max_final_price=max_final_price
        )
        == 71
    )


# ---------------------------------------------------------------------------
# `final_price_bounds` / `score_listings`: atajo usado por los endpoints
# ---------------------------------------------------------------------------


def test_final_price_bounds_and_score_listings_use_the_visible_set():
    cheap = _listing(external_id="A", price=Decimal("100"), shipping_cost=Decimal("0"))
    expensive = _listing(external_id="B", price=Decimal("300"), shipping_cost=Decimal("0"))
    bounds = final_price_bounds([cheap, expensive])
    assert bounds.min_final_price == Decimal("100")
    assert bounds.max_final_price == Decimal("300")

    scores = score_listings([cheap, expensive])
    assert scores == [
        score_of(cheap, min_final_price=Decimal("100"), max_final_price=Decimal("300")),
        score_of(expensive, min_final_price=Decimal("100"), max_final_price=Decimal("300")),
    ]
    # La mas barata del set nunca puede puntuar peor en el eje precio que la mas cara.
    assert scores[0] >= scores[1]


def test_final_price_bounds_rejects_empty_set():
    with pytest.raises(ValueError):
        final_price_bounds([])
    assert score_listings([]) == []

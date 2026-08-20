"""Una publicacion sin precio no puede entrar al comparador."""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.adapters.types import NormalizedListingInput

BASE = {
    "source_slug": "cetrogar",
    "external_id": "abc-123",
    "title": "Placa de Video 8Gb Rtx 5060 Ti Msi Gaming Trio Oc GDDR7",
    "permalink": "https://www.cetrogar.com.ar/placa-de-video",
}


def test_precio_cero_se_rechaza():
    """Cero no es "gratis": es "esta tienda no publica precio" (sin stock).

    Aceptarlo lo vuelve el mas barato del grupo y el sitio anuncia un ahorro inventado.
    """
    with pytest.raises(ValidationError):
        NormalizedListingInput(**BASE, price=Decimal("0"))


def test_precio_negativo_se_rechaza():
    with pytest.raises(ValidationError):
        NormalizedListingInput(**BASE, price=Decimal("-1"))


def test_precio_positivo_entra():
    listing = NormalizedListingInput(**BASE, price=Decimal("1506799"))
    assert listing.price == Decimal("1506799")


def test_envio_gratis_sigue_siendo_cero():
    """El envio SI puede ser 0: ahi cero significa gratis, no "sin dato"."""
    listing = NormalizedListingInput(**BASE, price=Decimal("100"), shipping_cost=Decimal("0"))
    assert listing.shipping_cost == Decimal("0")

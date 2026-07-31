"""Schema de Cotejo.

Importar `app.models` registra TODAS las tablas en `Base.metadata`. Alembic depende de
esto (`alembic/env.py` importa este paquete y usa `Base.metadata` como target): si un
modelo nuevo no se re-exporta aca, `alembic revision --autogenerate` lo ignora en silencio
y peor, propone borrar la tabla.
"""

from app.models.base import Base
from app.models.listing import Listing
from app.models.price_history import PriceHistory
from app.models.product import Product
from app.models.product_match import ProductMatch
from app.models.retailer_source import RetailerSource
from app.models.saved_product import SavedProduct
from app.models.user_account import UserAccount
from app.models.user_event import UserEvent
from app.models.user_session import UserSession

__all__ = [
    "Base",
    "Listing",
    "PriceHistory",
    "Product",
    "ProductMatch",
    "RetailerSource",
    "SavedProduct",
    "UserAccount",
    "UserEvent",
    "UserSession",
]

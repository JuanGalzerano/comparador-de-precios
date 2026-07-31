"""Siembra una SQLite de archivo (`dev.db`) con datos de prueba, para poder levantar
`uvicorn` local y ver el sitio funcionando de punta a punta sin depender de un Postgres
real. Mismos datos que `tests/conftest.py` (cluster iphone + remera del mock).

Uso: `.venv/Scripts/python.exe scripts/seed_dev_db.py`
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.enums import ItemCondition, SourceKind, SourceStatus, WarrantyType
from app.models import Base  # importa el paquete completo: registra TODAS las tablas
from app.models.listing import Listing
from app.models.price_history import PriceHistory
from app.models.product import Product
from app.models.retailer_source import RetailerSource

DB_PATH = Path(__file__).resolve().parent.parent / "dev.db"


def main() -> None:
    if DB_PATH.exists():
        DB_PATH.unlink()

    engine = create_engine(f"sqlite:///{DB_PATH}")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    db = Session()

    rs = RetailerSource(slug="mercadolibre", kind=SourceKind.API, status=SourceStatus.ACTIVE)
    db.add(rs)
    db.flush()

    iphone = Product(
        canonical_title="Apple iPhone 13 128 GB",
        brand="Apple",
        model="iPhone 13",
        category="celulares",
        catalog_product_id="MLA22811322",
        attributes_json={"capacidad": "128GB", "color": "Midnight"},
    )
    db.add(iphone)
    db.flush()

    now = datetime.now(timezone.utc)
    listings_data = [
        dict(
            external_id="MLA-8821", seller_name="MacStation",
            title="iPhone 13 128GB Midnight — sellado",
            price=Decimal("1049000"), shipping_cost=Decimal("0"), fulfillment=True,
            installments_qty=12, installments_amount=Decimal("87416"), interest_free=True,
            seller_level="platinum", seller_sales=48200, official_store="Apple Premium Reseller",
            rating=Decimal("4.9"), reviews_count=1840, warranty_months=12,
            warranty_type=WarrantyType.OFICIAL, condition=ItemCondition.NEW,
        ),
        dict(
            external_id="MLA-4410", seller_name="Tecno Norte",
            title="Apple iPhone 13 128 GB azul medianoche",
            price=Decimal("989000"), shipping_cost=Decimal("0"), fulfillment=True,
            installments_qty=6, installments_amount=Decimal("164833"), interest_free=True,
            seller_level="gold", seller_sales=12400, official_store=None,
            rating=Decimal("4.7"), reviews_count=612, warranty_months=6,
            warranty_type=WarrantyType.VENDEDOR, condition=ItemCondition.NEW,
        ),
        dict(
            external_id="MLA-6120", seller_name="DistriTel",
            title="iPhone 13 128gb liberado importado",
            price=Decimal("934000"), shipping_cost=Decimal("22000"), fulfillment=False,
            installments_qty=1, installments_amount=Decimal("956000"), interest_free=False,
            seller_level="silver", seller_sales=340, official_store=None,
            rating=Decimal("3.8"), reviews_count=41, warranty_months=0,
            warranty_type=WarrantyType.SIN, condition=ItemCondition.NEW,
        ),
        dict(
            external_id="MLA-1904", seller_name="Punto Celular",
            title="iPhone 13 128 GB usado, 92% bateria",
            price=Decimal("690000"), shipping_cost=Decimal("12000"), fulfillment=False,
            installments_qty=6, installments_amount=Decimal("117000"), interest_free=False,
            seller_level="gold", seller_sales=4200, official_store=None,
            rating=Decimal("4.3"), reviews_count=205, warranty_months=3,
            warranty_type=WarrantyType.VENDEDOR, condition=ItemCondition.USED,
        ),
    ]
    listings = []
    for data in listings_data:
        listing = Listing(
            product_id=iphone.id, retailer_source_id=rs.id,
            permalink=f"https://articulo.mercadolibre.com.ar/{data['external_id']}",
            fetched_at=now, **data,
        )
        db.add(listing)
        listings.append(listing)
    db.flush()

    cheapest = next(item for item in listings if item.external_id == "MLA-1904")
    db.add_all([
        PriceHistory(listing_id=cheapest.id, price=Decimal("710000"),
                     shipping_cost=Decimal("12000"), captured_at=now - timedelta(days=120)),
        PriceHistory(listing_id=cheapest.id, price=Decimal("690000"),
                     shipping_cost=Decimal("12000"), captured_at=now - timedelta(days=5)),
    ])

    remera = Product(
        canonical_title="Remera Nike Sportswear Club — hombre",
        brand="Nike", model="Sportswear Club", category="indumentaria",
    )
    db.add(remera)
    db.flush()
    db.add(Listing(
        product_id=remera.id, retailer_source_id=rs.id, external_id="MLA-2210",
        seller_name="Nike Store", title="Remera Nike Sportswear Club negra — tienda oficial",
        permalink="https://articulo.mercadolibre.com.ar/MLA-2210",
        price=Decimal("42999"), shipping_cost=Decimal("0"), fulfillment=True,
        installments_qty=6, installments_amount=Decimal("7166"), interest_free=True,
        seller_level="platinum", seller_sales=320000, official_store="Nike",
        rating=Decimal("4.8"), reviews_count=8900, warranty_months=3,
        warranty_type=WarrantyType.OFICIAL, condition=ItemCondition.NEW,
        fetched_at=now,
    ))
    db.commit()
    print(f"OK: {DB_PATH} sembrada con producto iphone (id={iphone.id}) y remera (id={remera.id})")


if __name__ == "__main__":
    main()

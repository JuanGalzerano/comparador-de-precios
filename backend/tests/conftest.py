"""Fixtures compartidas de los tests de endpoints (`/search`, `/products`).

Postgres no esta alcanzable en este sandbox: `psycopg2.connect` a
`localhost:5432` devuelve `Connection refused` (verificado a mano antes de escribir
estos tests). Los tests de endpoints corren entonces contra SQLite en memoria.

Nota sobre `listing.final_price` (columna GENERATED, `Computed` en
`app/models/listing.py`): se verifico a mano, ANTES de asumir que hacia falta un
workaround, que SQLAlchemy traduce ese `Computed` a
`GENERATED ALWAYS AS (price + coalesce(shipping_cost, 0)) STORED` tambien en SQLite
(soportado desde SQLite 3.31, que es lo que trae cualquier Python 3.11+ moderno) y que
el valor se lee bien tanto recien insertado como despues de `commit()` con
`expire_on_commit=False` (la config real de `app/db.py`). Por eso NINGUN fixture de
aca calcula `final_price` a mano en Python: no hace falta. Se documenta este punto en
vez de dejarlo como un supuesto silencioso, tal como pide la tarea.

Los datos sembrados son un subconjunto fiel de `catalog().iphone` y `catalog().remera`
del mock (`project/Cotejo - Comparador.dc.html:507-524` y `539-551`): mismos ids
(`MLA-8821`, ...), mismos precios/atributos, para que cualquier discrepancia contra un
calculo hecho a mano sobre el mock sea detectable.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.deps import get_db
from app.enums import ItemCondition, SourceKind, SourceStatus, WarrantyType
from app.main import app
from app.models.base import Base
from app.models.listing import Listing
from app.models.price_history import PriceHistory
from app.models.product import Product
from app.models.retailer_source import RetailerSource
from app.models.saved_product import SavedProduct
from app.models.user_account import UserAccount
from app.models.user_session import UserSession

# Nota: NO se hace `import app.models` aca (rebindearia el nombre `app` de este
# modulo al PAQUETE `app`, pisando el `from app.main import app` de arriba, que es la
# instancia de FastAPI que necesita el fixture `client`). Los modelos que estos tests
# usan (`Product`, `Listing`, `PriceHistory`, `RetailerSource`, `UserAccount`,
# `UserSession`, `SavedProduct`) ya quedan registrados en `Base.metadata` con los
# imports de arriba, y transitivamente por `from app.main import app` (que importa los
# routers, que importan estos mismos modulos de `app.models`).


@pytest.fixture()
def db_engine():
    """SQLite en memoria, con `StaticPool` para que la misma conexion (y por lo tanto
    la misma base en memoria) sobreviva entre el fixture de sesion y el request de
    `TestClient` (una conexion nueva a `sqlite:///:memory:` es una base vacia nueva)."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture()
def db_session(db_engine) -> Iterator[Session]:
    testing_session_local = sessionmaker(
        bind=db_engine, autoflush=False, autocommit=False, expire_on_commit=False
    )
    session = testing_session_local()
    try:
        yield session
    finally:
        session.close()


def _seed_iphone_cluster(db: Session) -> tuple[Product, list[Listing]]:
    """Subset de 4 publicaciones del cluster `iphone` del mock: alcanza para ejercitar
    sort/filtros/score sin transcribir las 10 publicaciones completas."""
    rs = RetailerSource(slug="mercadolibre", kind=SourceKind.API, status=SourceStatus.ACTIVE)
    db.add(rs)
    db.flush()

    product = Product(
        canonical_title="Apple iPhone 13 128 GB",
        brand="Apple",
        model="iPhone 13",
        category="celulares",
        catalog_product_id="MLA22811322",
        attributes_json={"capacidad": "128GB", "color": "Midnight"},
    )
    db.add(product)
    db.flush()

    now = datetime.now(timezone.utc)
    listings_data = [
        dict(
            external_id="MLA-8821",
            seller_name="MacStation",
            title="iPhone 13 128GB Midnight — sellado",
            price=Decimal("1049000"),
            shipping_cost=Decimal("0"),
            fulfillment=True,
            installments_qty=12,
            installments_amount=Decimal("87416"),
            interest_free=True,
            seller_level="platinum",
            seller_sales=48200,
            official_store="Apple Premium Reseller",
            rating=Decimal("4.9"),
            reviews_count=1840,
            warranty_months=12,
            warranty_type=WarrantyType.OFICIAL,
            condition=ItemCondition.NEW,
        ),
        dict(
            external_id="MLA-4410",
            seller_name="Tecno Norte",
            title="Apple iPhone 13 128 GB azul medianoche",
            price=Decimal("989000"),
            shipping_cost=Decimal("0"),
            fulfillment=True,
            installments_qty=6,
            installments_amount=Decimal("164833"),
            interest_free=True,
            seller_level="gold",
            seller_sales=12400,
            official_store=None,
            rating=Decimal("4.7"),
            reviews_count=612,
            warranty_months=6,
            warranty_type=WarrantyType.VENDEDOR,
            condition=ItemCondition.NEW,
        ),
        dict(
            external_id="MLA-6120",
            seller_name="DistriTel",
            title="iPhone 13 128gb liberado importado",
            price=Decimal("934000"),
            shipping_cost=Decimal("22000"),
            fulfillment=False,
            installments_qty=1,
            installments_amount=Decimal("956000"),
            interest_free=False,
            seller_level="silver",
            seller_sales=340,
            official_store=None,
            rating=Decimal("3.8"),
            reviews_count=41,
            warranty_months=0,
            warranty_type=WarrantyType.SIN,
            condition=ItemCondition.NEW,
        ),
        dict(
            external_id="MLA-1904",
            seller_name="Punto Celular",
            title="iPhone 13 128 GB usado, 92% bateria",
            price=Decimal("690000"),
            shipping_cost=Decimal("12000"),
            fulfillment=False,
            installments_qty=6,
            installments_amount=Decimal("117000"),
            interest_free=False,
            seller_level="gold",
            seller_sales=4200,
            official_store=None,
            rating=Decimal("4.3"),
            reviews_count=205,
            warranty_months=3,
            warranty_type=WarrantyType.VENDEDOR,
            condition=ItemCondition.USED,
        ),
    ]
    listings: list[Listing] = []
    for data in listings_data:
        listing = Listing(
            product_id=product.id,
            retailer_source_id=rs.id,
            permalink=f"https://articulo.mercadolibre.com.ar/{data['external_id']}",
            fetched_at=now,
            **data,
        )
        db.add(listing)
        listings.append(listing)
    db.flush()

    # Historial de precio del listing mas barato: un snapshot reciente y uno de hace
    # 120 dias (fuera de la ventana default de 90), para poder verificar el corte de
    # tiempo de `/price-history` sin ambiguedad.
    cheapest = next(item for item in listings if item.external_id == "MLA-1904")
    db.add_all(
        [
            PriceHistory(
                listing_id=cheapest.id,
                price=Decimal("710000"),
                shipping_cost=Decimal("12000"),
                captured_at=now - timedelta(days=120),
            ),
            PriceHistory(
                listing_id=cheapest.id,
                price=Decimal("690000"),
                shipping_cost=Decimal("12000"),
                captured_at=now - timedelta(days=5),
            ),
        ]
    )
    db.commit()
    db.refresh(product)
    for listing in listings:
        db.refresh(listing)
    return product, listings


def _seed_remera_cluster(db: Session) -> Product:
    """Segundo cluster, con categoria distinta (`indumentaria`): habilita probar el
    filtro de `category` y la paginacion sobre mas de un producto en `/search`."""
    existing_source = db.query(RetailerSource).filter_by(slug="mercadolibre").first()
    if existing_source is None:
        existing_source = RetailerSource(
            slug="mercadolibre", kind=SourceKind.API, status=SourceStatus.ACTIVE
        )
        db.add(existing_source)
        db.flush()

    product = Product(
        canonical_title="Remera Nike Sportswear Club — hombre",
        brand="Nike",
        model="Sportswear Club",
        category="indumentaria",
    )
    db.add(product)
    db.flush()

    listing = Listing(
        product_id=product.id,
        retailer_source_id=existing_source.id,
        external_id="MLA-2210",
        seller_name="Nike Store",
        title="Remera Nike Sportswear Club negra — tienda oficial",
        permalink="https://articulo.mercadolibre.com.ar/MLA-2210",
        price=Decimal("42999"),
        shipping_cost=Decimal("0"),
        fulfillment=True,
        installments_qty=6,
        installments_amount=Decimal("7166"),
        interest_free=True,
        seller_level="platinum",
        seller_sales=320000,
        official_store="Nike",
        rating=Decimal("4.8"),
        reviews_count=8900,
        warranty_months=3,
        warranty_type=WarrantyType.OFICIAL,
        condition=ItemCondition.NEW,
        fetched_at=datetime.now(timezone.utc),
    )
    db.add(listing)
    db.commit()
    db.refresh(product)
    return product


@pytest.fixture()
def seeded_db(db_session: Session) -> Session:
    """DB con el cluster `iphone` (principal, 4 publicaciones) y `remera`
    (secundario, 1 publicacion) sembrados."""
    _seed_iphone_cluster(db_session)
    _seed_remera_cluster(db_session)
    return db_session


@pytest.fixture()
def client(db_session: Session) -> Iterator[TestClient]:
    """`TestClient` con `get_db` sobreescrito para usar la MISMA sesion de test.

    `db_session` es function-scoped: cuando un test pide `client` y `seeded_db` a la
    vez, pytest resuelve `db_session` una sola vez y ambos fixtures comparten la
    misma instancia, asi los datos sembrados son visibles para las requests.
    """

    def _override_get_db() -> Iterator[Session]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)

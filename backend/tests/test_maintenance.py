"""Tests de la política de reemplazo del caché (`app/services/maintenance.py`).

Lo que se prueba es la política, no la implementación: qué sobrevive y qué no. Un error
acá se traduce en borrar datos que la gente usa, así que cada regla tiene su test.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.enums import ItemCondition, SourceKind, SourceStatus, WarrantyType
from app.models.listing import Listing
from app.models.price_history import PriceHistory
from app.models.product import Product
from app.models.retailer_source import RetailerSource
from app.models.saved_product import SavedProduct
from app.models.user_account import UserAccount
from app.services import maintenance


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _source(db: Session) -> RetailerSource:
    source = RetailerSource(
        slug="cetrogar",
        display_name="Cetrogar",
        kind=SourceKind.VTEX,
        status=SourceStatus.ACTIVE,
        config_json={},
    )
    db.add(source)
    db.flush()
    return source


def _product(
    db: Session,
    title: str,
    *,
    created_days_ago: int = 30,
    accessed_days_ago: int | None = None,
    access_count: int = 0,
) -> Product:
    product = Product(
        canonical_title=title,
        attributes_json={},
        access_count=access_count,
        last_accessed_at=(
            _now() - timedelta(days=accessed_days_ago) if accessed_days_ago is not None else None
        ),
    )
    db.add(product)
    db.flush()
    # `created_at` lo pone la base con un default: se pisa después del flush.
    product.created_at = _now() - timedelta(days=created_days_ago)
    db.flush()
    return product


def _listing(db: Session, source: RetailerSource, product: Product, price: str = "1000") -> Listing:
    listing = Listing(
        product_id=product.id,
        retailer_source_id=source.id,
        external_id=f"ext-{product.id}",
        title=product.canonical_title,
        permalink="https://example.test/x",
        condition=ItemCondition.NEW,
        price=Decimal(price),
        warranty_type=WarrantyType.UNKNOWN,
        fetched_at=_now(),
    )
    db.add(listing)
    db.flush()
    return listing


# --- Capa 1: retención del historial ---------------------------------------


def test_purge_keeps_the_last_90_days(db_session: Session) -> None:
    source = _source(db_session)
    product = _product(db_session, "Heladera")
    listing = _listing(db_session, source, product)

    for days in (200, 150, 100, 80, 10, 1):
        db_session.add(
            PriceHistory(
                listing_id=listing.id,
                price=Decimal("1000"),
                captured_at=_now() - timedelta(days=days),
            )
        )
    db_session.commit()

    deleted = maintenance.purge_price_history(db_session, days=90)

    quedan = db_session.scalars(select(PriceHistory.captured_at)).all()
    assert deleted == 3  # 200, 150 y 100 días
    assert len(quedan) == 3
    # SQLite devuelve datetimes sin zona horaria (Postgres los devuelve aware): se
    # normaliza antes de comparar, mismo criterio que `app/api/deps.py`.
    limite = _now() - timedelta(days=91)
    assert all(
        (c if c.tzinfo else c.replace(tzinfo=timezone.utc)) >= limite for c in quedan
    )


def test_purge_never_leaves_a_listing_without_history(db_session: Session) -> None:
    """El punto más reciente sobrevive aunque sea viejo: es la base de comparación."""
    source = _source(db_session)
    product = _product(db_session, "Lavarropas que no cambia de precio")
    listing = _listing(db_session, source, product)
    db_session.add(
        PriceHistory(
            listing_id=listing.id,
            price=Decimal("1000"),
            captured_at=_now() - timedelta(days=300),
        )
    )
    db_session.commit()

    maintenance.purge_price_history(db_session, days=90)

    assert db_session.scalar(select(func.count(PriceHistory.id))) == 1


# --- Capa 2: evicción -------------------------------------------------------


def test_evicts_cold_and_unpopular(db_session: Session) -> None:
    source = _source(db_session)
    frio = _product(db_session, "Producto que nadie miró", accessed_days_ago=None)
    _listing(db_session, source, frio)
    db_session.commit()

    result = maintenance.evict_cold_products(db_session)

    assert result.products_deleted == 1
    assert result.listings_deleted == 1
    assert db_session.scalar(select(func.count(Product.id))) == 0
    assert db_session.scalar(select(func.count(Listing.id))) == 0


def test_popular_products_survive_even_when_cold(db_session: Session) -> None:
    """Frecuencia, no solo recencia: lo muy buscado se queda aunque tenga unos días."""
    _source(db_session)
    popular = _product(db_session, "iPhone que se busca siempre", accessed_days_ago=60, access_count=50)
    db_session.commit()

    maintenance.evict_cold_products(db_session)

    assert db_session.get(Product, popular.id) is not None


def test_recently_used_products_survive(db_session: Session) -> None:
    _source(db_session)
    reciente = _product(db_session, "Buscado ayer", accessed_days_ago=1, access_count=1)
    db_session.commit()

    maintenance.evict_cold_products(db_session)

    assert db_session.get(Product, reciente.id) is not None


def test_new_products_get_a_grace_period(db_session: Session) -> None:
    """Recién traído y todavía sin visitas no es basura: nunca tuvo la oportunidad."""
    _source(db_session)
    nuevo = _product(db_session, "Traído hoy", created_days_ago=0, accessed_days_ago=None)
    db_session.commit()

    maintenance.evict_cold_products(db_session)

    assert db_session.get(Product, nuevo.id) is not None


def test_saved_products_are_never_evicted(db_session: Session) -> None:
    """Lo que un usuario guardó no se borra, por más frío que esté."""
    source = _source(db_session)
    guardado = _product(db_session, "Guardado por alguien", accessed_days_ago=None)
    _listing(db_session, source, guardado)
    user = UserAccount(email="juan@example.test", password_hash="x")
    db_session.add(user)
    db_session.flush()
    db_session.add(SavedProduct(user_id=user.id, product_id=guardado.id))
    db_session.commit()

    result = maintenance.evict_cold_products(db_session)

    assert result.products_deleted == 0
    assert db_session.get(Product, guardado.id) is not None


def test_eviction_deletes_the_worst_first(db_session: Session) -> None:
    """Con cupo limitado se borra lo peor: menos accedido y más viejo."""
    _source(db_session)
    basura = _product(db_session, "Cero accesos", accessed_days_ago=None, access_count=0)
    intermedio = _product(db_session, "Un acceso viejo", accessed_days_ago=200, access_count=1)
    db_session.commit()

    maintenance.evict_cold_products(db_session, limit=1)

    assert db_session.get(Product, basura.id) is None
    assert db_session.get(Product, intermedio.id) is not None


def test_touch_products_records_usage(db_session: Session) -> None:
    _source(db_session)
    product = _product(db_session, "Algo", accessed_days_ago=None)
    db_session.commit()

    maintenance.touch_products(db_session, [product.id])
    maintenance.touch_products(db_session, [product.id])

    db_session.refresh(product)
    assert product.access_count == 2
    assert product.last_accessed_at is not None


def test_search_marks_results_as_used(db_session: Session, client: TestClient, seeded_db: Session) -> None:
    """El circuito real: buscar algo cuenta como usarlo, y eso lo protege."""
    antes = db_session.scalars(select(Product.access_count)).all()

    client.get("/search", params={"q": "iphone", "live": "false"})

    despues = db_session.scalars(select(Product.access_count)).all()
    assert sum(despues) > sum(antes)


# --- Capa 3: freno por cuota ------------------------------------------------


def test_should_persist_is_false_when_the_quota_is_reached(db_session: Session, monkeypatch) -> None:
    monkeypatch.setattr(
        maintenance, "database_size_bytes", lambda db: maintenance.settings.storage_quota_bytes
    )

    assert maintenance.should_persist(db_session) is False


def test_should_persist_is_true_with_room_to_spare(db_session: Session, monkeypatch) -> None:
    monkeypatch.setattr(maintenance, "database_size_bytes", lambda db: 1_000_000)

    assert maintenance.should_persist(db_session) is True


@pytest.mark.parametrize(
    "percent,evicting,read_only",
    [(10.0, False, False), (80.0, True, False), (95.0, True, True)],
)
def test_storage_thresholds(
    db_session: Session, monkeypatch, percent: float, evicting: bool, read_only: bool
) -> None:
    quota = maintenance.settings.storage_quota_bytes
    monkeypatch.setattr(maintenance, "database_size_bytes", lambda db: int(quota * percent / 100))

    status = maintenance.storage_status(db_session)

    assert status.should_evict is evicting
    assert status.should_stop_writing is read_only


def test_storage_endpoint_reports_usage(client: TestClient) -> None:
    body = client.get("/health/storage").json()

    assert body["quota_mb"] > 0
    assert 0 <= body["used_percent"] <= 100
    assert body["read_only"] is False

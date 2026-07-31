"""initial schema

Schema nucleo de Cotejo: retailer_source, product, listing, price_history,
product_match, user_event.

Generada con `alembic revision --autogenerate` a partir de `app.models` y corregida a mano
para Postgres (ver notas al pie de este docstring), porque en el entorno donde se creo no
habia una instancia de Postgres alcanzable y el autogenerate corrio contra SQLite.

Correcciones aplicadas sobre la salida del autogenerate:
- `postgresql.JSONB(astext_type=Text())` -> `sa.Text()` (el original no importaba `Text`
  y rompia con NameError).
- `server_default=sa.text('(CURRENT_TIMESTAMP)')` -> `sa.func.now()`, que es lo que
  declaran los modelos; si no, `compare_server_default` marca diff en cada autogenerate.
- `server_default=sa.text('(false)')` -> `sa.text('false')`.
- `downgrade()` dropea explicitamente los ENUM de Postgres: `op.drop_table` NO dropea el
  tipo, y sin esto un `downgrade` + `upgrade` falla con "type already exists".

Revision ID: 7366f151098f
Revises:
Create Date: 2026-07-30 13:28:35.629499

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "7366f151098f"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Los tipos ENUM los crea implicitamente el primer `create_table` que los usa
# (cada uno se usa en una sola tabla). Se listan aca para poder dropearlos en downgrade.
ENUM_TYPE_NAMES = (
    "source_kind",
    "source_status",
    "item_condition",
    "warranty_type",
    "match_method",
)

JSONB_TYPE = postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite")
BIG_ID = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
MONEY = sa.Numeric(precision=14, scale=2)


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "product",
        sa.Column("id", BIG_ID, autoincrement=True, nullable=False),
        sa.Column("canonical_title", sa.String(length=512), nullable=False),
        sa.Column("brand", sa.String(length=128), nullable=True),
        sa.Column("model", sa.String(length=128), nullable=True),
        sa.Column("category", sa.String(length=128), nullable=True),
        sa.Column("catalog_product_id", sa.String(length=64), nullable=True),
        sa.Column("attributes_json", JSONB_TYPE, server_default="{}", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_product")),
        sa.UniqueConstraint("catalog_product_id", name=op.f("uq_product_catalog_product_id")),
    )
    op.create_index("ix_product_brand_model", "product", ["brand", "model"], unique=False)
    op.create_index("ix_product_category", "product", ["category"], unique=False)

    op.create_table(
        "retailer_source",
        sa.Column("id", BIG_ID, autoincrement=True, nullable=False),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=128), nullable=True),
        sa.Column(
            "kind",
            sa.Enum("api", "vtex", "sepa_feed", "scraper", name="source_kind"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "active",
                "disabled",
                "experimental",
                "blocked_tos_review",
                name="source_status",
            ),
            server_default="experimental",
            nullable=False,
        ),
        sa.Column("tos_risk_note", sa.Text(), nullable=True),
        sa.Column("config_json", JSONB_TYPE, server_default="{}", nullable=False),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_retailer_source")),
        sa.UniqueConstraint("slug", name=op.f("uq_retailer_source_slug")),
    )
    op.create_index(
        "ix_retailer_source_status_kind", "retailer_source", ["status", "kind"], unique=False
    )

    op.create_table(
        "listing",
        sa.Column("id", BIG_ID, autoincrement=True, nullable=False),
        sa.Column("product_id", BIG_ID, nullable=True),
        sa.Column("retailer_source_id", BIG_ID, nullable=False),
        sa.Column("external_id", sa.String(length=128), nullable=False),
        sa.Column("seller_name", sa.String(length=256), nullable=True),
        sa.Column("seller_id", sa.String(length=64), nullable=True),
        sa.Column("seller_level", sa.String(length=32), nullable=True),
        sa.Column("seller_sales", sa.Integer(), nullable=True),
        sa.Column("official_store", sa.String(length=128), nullable=True),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column(
            "condition",
            sa.Enum("new", "used", "refurbished", "unknown", name="item_condition"),
            server_default="unknown",
            nullable=False,
        ),
        sa.Column("permalink", sa.Text(), nullable=False),
        sa.Column("price", MONEY, nullable=False),
        sa.Column("shipping_cost", MONEY, nullable=True),
        sa.Column(
            "final_price",
            MONEY,
            sa.Computed("price + coalesce(shipping_cost, 0)", persisted=True),
            nullable=False,
        ),
        sa.Column("installments_qty", sa.SmallInteger(), nullable=True),
        sa.Column("installments_amount", MONEY, nullable=True),
        sa.Column("interest_free", sa.Boolean(), nullable=True),
        sa.Column("fulfillment", sa.Boolean(), nullable=True),
        sa.Column("rating", sa.Numeric(precision=3, scale=2), nullable=True),
        sa.Column("reviews_count", sa.Integer(), nullable=True),
        sa.Column("warranty_months", sa.SmallInteger(), nullable=True),
        sa.Column(
            "warranty_type",
            sa.Enum("oficial", "vendedor", "sin", "unknown", name="warranty_type"),
            server_default="unknown",
            nullable=False,
        ),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("price >= 0", name=op.f("ck_listing_price_non_negative")),
        sa.CheckConstraint(
            "rating IS NULL OR (rating >= 0 AND rating <= 5)",
            name=op.f("ck_listing_rating_range"),
        ),
        sa.CheckConstraint(
            "shipping_cost IS NULL OR shipping_cost >= 0",
            name=op.f("ck_listing_shipping_cost_non_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["product.id"],
            name=op.f("fk_listing_product_id_product"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["retailer_source_id"],
            ["retailer_source.id"],
            name=op.f("fk_listing_retailer_source_id_retailer_source"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_listing")),
        # Clave natural de upsert de la ingesta.
        sa.UniqueConstraint(
            "retailer_source_id", "external_id", name="uq_listing_source_external"
        ),
    )
    op.create_index(
        "ix_listing_product_id_final_price", "listing", ["product_id", "final_price"], unique=False
    )
    op.create_index(
        "ix_listing_retailer_source_id_fetched_at",
        "listing",
        ["retailer_source_id", "fetched_at"],
        unique=False,
    )

    op.create_table(
        "price_history",
        sa.Column("id", BIG_ID, autoincrement=True, nullable=False),
        sa.Column("listing_id", BIG_ID, nullable=False),
        sa.Column("price", MONEY, nullable=False),
        sa.Column("shipping_cost", MONEY, nullable=True),
        sa.Column(
            "captured_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("price >= 0", name=op.f("ck_price_history_price_non_negative")),
        sa.ForeignKeyConstraint(
            ["listing_id"],
            ["listing.id"],
            name=op.f("fk_price_history_listing_id_listing"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_price_history")),
    )
    op.create_index(
        "ix_price_history_listing_id_captured_at",
        "price_history",
        ["listing_id", "captured_at"],
        unique=False,
    )

    op.create_table(
        "product_match",
        sa.Column("id", BIG_ID, autoincrement=True, nullable=False),
        sa.Column("listing_id", BIG_ID, nullable=False),
        sa.Column("product_id", BIG_ID, nullable=False),
        sa.Column(
            "method",
            sa.Enum("catalog_id", "fuzzy", "embedding", "manual", name="match_method"),
            nullable=False,
        ),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column(
            "reviewed_by_human", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1", name=op.f("ck_product_match_confidence_range")
        ),
        sa.ForeignKeyConstraint(
            ["listing_id"],
            ["listing.id"],
            name=op.f("fk_product_match_listing_id_listing"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["product.id"],
            name=op.f("fk_product_match_product_id_product"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_product_match")),
        sa.UniqueConstraint(
            "listing_id", "product_id", name="uq_product_match_listing_product"
        ),
    )
    op.create_index("ix_product_match_product_id", "product_match", ["product_id"], unique=False)
    op.create_index(
        "ix_product_match_reviewed_by_human_confidence",
        "product_match",
        ["reviewed_by_human", "confidence"],
        unique=False,
    )

    op.create_table(
        "user_event",
        sa.Column("id", BIG_ID, autoincrement=True, nullable=False),
        sa.Column("anon_id", sa.String(length=64), nullable=False),
        sa.Column("type", sa.String(length=48), nullable=False),
        sa.Column("product_id", BIG_ID, nullable=True),
        sa.Column("listing_id", BIG_ID, nullable=True),
        sa.Column("payload_json", JSONB_TYPE, server_default="{}", nullable=False),
        sa.Column(
            "ts", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["listing_id"],
            ["listing.id"],
            name=op.f("fk_user_event_listing_id_listing"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["product.id"],
            name=op.f("fk_user_event_product_id_product"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_user_event")),
    )
    op.create_index("ix_user_event_anon_id_ts", "user_event", ["anon_id", "ts"], unique=False)
    op.create_index("ix_user_event_product_id_ts", "user_event", ["product_id", "ts"], unique=False)
    op.create_index("ix_user_event_type_ts", "user_event", ["type", "ts"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_user_event_type_ts", table_name="user_event")
    op.drop_index("ix_user_event_product_id_ts", table_name="user_event")
    op.drop_index("ix_user_event_anon_id_ts", table_name="user_event")
    op.drop_table("user_event")

    op.drop_index("ix_product_match_reviewed_by_human_confidence", table_name="product_match")
    op.drop_index("ix_product_match_product_id", table_name="product_match")
    op.drop_table("product_match")

    op.drop_index("ix_price_history_listing_id_captured_at", table_name="price_history")
    op.drop_table("price_history")

    op.drop_index("ix_listing_retailer_source_id_fetched_at", table_name="listing")
    op.drop_index("ix_listing_product_id_final_price", table_name="listing")
    op.drop_table("listing")

    op.drop_index("ix_retailer_source_status_kind", table_name="retailer_source")
    op.drop_table("retailer_source")

    op.drop_index("ix_product_category", table_name="product")
    op.drop_index("ix_product_brand_model", table_name="product")
    op.drop_table("product")

    # `op.drop_table` no dropea los tipos ENUM en Postgres: sin esto, un
    # downgrade + upgrade falla con "type ... already exists".
    if op.get_bind().dialect.name == "postgresql":
        for type_name in ENUM_TYPE_NAMES:
            op.execute(sa.text(f'DROP TYPE IF EXISTS "{type_name}"'))

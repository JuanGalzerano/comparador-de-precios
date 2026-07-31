"""add user accounts, sessions and saved products

Cuentas de usuario, sesiones opacas y favoritos: `user_account`, `user_session`,
`saved_product`.

Generada con `alembic revision --autogenerate` y corregida a mano por la misma razon que
la migracion inicial (`7366f151098f_initial_schema.py`): en este sandbox Postgres no esta
alcanzable (`socket.connect(("localhost", 5432))` da timeout, verificado a mano antes de
generar), asi que el autogenerate corrio contra SQLite.

Correcciones aplicadas sobre la salida del autogenerate (mismas dos que la migracion
inicial):
- `server_default=sa.text('(CURRENT_TIMESTAMP)')` -> `sa.func.now()`, que es lo que
  declaran los modelos (`TimestampMixin`, `UserSession.created_at`,
  `SavedProduct.created_at`); si no, `compare_server_default` marca diff en cada
  autogenerate futuro.
- `server_default=sa.text('(true)')` -> `sa.text('true')` (`UserAccount.is_active`).

A diferencia de la migracion inicial, esta NO crea ningun tipo ENUM de Postgres (ninguno
de los tres modelos nuevos usa `pg_enum`), asi que `downgrade()` no necesita el
`DROP TYPE` extra: son sencillamente los tres `drop_table` en orden inverso al `upgrade`.

Revision ID: 11112c1be0cd
Revises: 7366f151098f
Create Date: 2026-07-30 14:58:08.576536

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "11112c1be0cd"
down_revision: Union[str, Sequence[str], None] = "7366f151098f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

BIG_ID = sa.BigInteger().with_variant(sa.Integer(), "sqlite")


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "user_account",
        sa.Column("id", BIG_ID, autoincrement=True, nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("display_name", sa.String(length=80), nullable=True),
        sa.Column(
            "is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("email = lower(email)", name=op.f("ck_user_account_email_lowercase")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_user_account")),
        sa.UniqueConstraint("email", name=op.f("uq_user_account_email")),
    )

    op.create_table(
        "saved_product",
        sa.Column("id", BIG_ID, autoincrement=True, nullable=False),
        sa.Column("user_id", BIG_ID, nullable=False),
        sa.Column("product_id", BIG_ID, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["product.id"],
            name=op.f("fk_saved_product_product_id_product"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["user_account.id"],
            name=op.f("fk_saved_product_user_id_user_account"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_saved_product")),
        sa.UniqueConstraint("user_id", "product_id", name="uq_saved_product_user_product"),
    )
    op.create_index(
        "ix_saved_product_user_id_created_at", "saved_product", ["user_id", "created_at"],
        unique=False,
    )

    op.create_table(
        "user_session",
        sa.Column("id", BIG_ID, autoincrement=True, nullable=False),
        sa.Column("user_id", BIG_ID, nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["user_account.id"],
            name=op.f("fk_user_session_user_id_user_account"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_user_session")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_user_session_token_hash")),
    )
    op.create_index("ix_user_session_expires_at", "user_session", ["expires_at"], unique=False)
    op.create_index("ix_user_session_user_id", "user_session", ["user_id"], unique=False)


def downgrade() -> None:
    """Downgrade schema. Sin tipos ENUM que dropear (ver docstring del modulo)."""
    op.drop_index("ix_user_session_user_id", table_name="user_session")
    op.drop_index("ix_user_session_expires_at", table_name="user_session")
    op.drop_table("user_session")

    op.drop_index("ix_saved_product_user_id_created_at", table_name="saved_product")
    op.drop_table("saved_product")

    op.drop_table("user_account")

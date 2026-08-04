"""add listing.catalog_product_id

Revision ID: a613b2182ee2
Revises: 11112c1be0cd
Create Date: 2026-08-04 16:59:06.914872

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a613b2182ee2'
down_revision: Union[str, Sequence[str], None] = '11112c1be0cd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('listing', sa.Column('catalog_product_id', sa.String(length=64), nullable=True))
    # El matcher agrupa por este valor: sin indice es un seq scan por publicacion.
    op.create_index(
        'ix_listing_catalog_product_id', 'listing', ['catalog_product_id'], unique=False
    )
    # `/sources` agrupa por (product_id, retailer_source_id) y toma min(final_price).
    # El indice existente es (product_id, final_price): le falta la fuente, asi que
    # Postgres hacia Seq Scan de toda la tabla en un endpoint que consume la home.
    op.create_index(
        'ix_listing_product_retailer_price',
        'listing',
        ['product_id', 'retailer_source_id', 'final_price'],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_listing_product_retailer_price', table_name='listing')
    op.drop_index('ix_listing_catalog_product_id', table_name='listing')
    op.drop_column('listing', 'catalog_product_id')

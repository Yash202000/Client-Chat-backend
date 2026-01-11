"""Add API to TriggerChannel enum

Revision ID: d3e4f5g6h7i8
Revises: c2d3e4f5g6h7
Create Date: 2026-01-10

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd3e4f5g6h7i8'
down_revision: Union[str, None] = 'c2d3e4f5g6h7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add 'API' value to the triggerchannel enum type in PostgreSQL
    # Using raw SQL because Alembic doesn't directly support enum modifications
    # Note: SQLAlchemy uses the enum member name (API) not value (api) for PostgreSQL enums
    op.execute("ALTER TYPE triggerchannel ADD VALUE IF NOT EXISTS 'API'")


def downgrade() -> None:
    # Note: PostgreSQL doesn't support removing enum values directly
    # To truly downgrade, you would need to:
    # 1. Create a new enum type without 'api'
    # 2. Update the column to use the new type
    # 3. Drop the old enum type
    # 4. Rename the new type
    # This is a destructive operation and not recommended
    pass

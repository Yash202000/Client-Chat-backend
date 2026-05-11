"""add workflow cached_embedding column

Revision ID: h3i4j5k6l7m8
Revises: g2h3i4j5k6l7
Create Date: 2026-05-11

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy import Float

revision = 'h3i4j5k6l7m8'
down_revision = 'g2h3i4j5k6l7'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('workflows', sa.Column('cached_embedding', ARRAY(Float), nullable=True))


def downgrade():
    op.drop_column('workflows', 'cached_embedding')

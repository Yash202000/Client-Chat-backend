"""add date_overrides to booking_links

Revision ID: i4j5k6l7m8n9
Revises: h3i4j5k6l7m8
Create Date: 2026-05-15
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = 'i4j5k6l7m8n9'
down_revision = '44adc5e38185'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'booking_links',
        sa.Column('date_overrides', JSONB, nullable=True, server_default='{}'),
    )


def downgrade():
    op.drop_column('booking_links', 'date_overrides')

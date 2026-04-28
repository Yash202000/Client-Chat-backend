"""add location and is_all_day to calendar_events

Revision ID: n3o4p5q6r7s8
Revises: m2n3o4p5q6r7
Create Date: 2026-04-28
"""
from alembic import op
import sqlalchemy as sa

revision = 'n3o4p5q6r7s8'
down_revision = 'm2n3o4p5q6r7'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('calendar_events', sa.Column('location', sa.String(500), nullable=True))
    op.add_column('calendar_events', sa.Column('is_all_day', sa.Boolean(), nullable=False, server_default=sa.text('false')))


def downgrade():
    op.drop_column('calendar_events', 'is_all_day')
    op.drop_column('calendar_events', 'location')

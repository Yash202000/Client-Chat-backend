"""calendar_events: add missing location and is_all_day columns

These were added in n3o4p5q6r7s8 but that migration was stamped without
being executed (the table already existed), so the columns are absent.

Revision ID: q6r7s8t9u0v1
Revises: p5q6r7s8t9u0
Create Date: 2026-04-28
"""
from alembic import op
import sqlalchemy as sa

revision = 'q6r7s8t9u0v1'
down_revision = 'p5q6r7s8t9u0'
branch_labels = None
depends_on = None


def upgrade():
    # Use IF NOT EXISTS so the migration is safe to run even if columns
    # somehow already exist (e.g. on a fresh env that ran all migrations).
    op.execute("ALTER TABLE calendar_events ADD COLUMN IF NOT EXISTS location VARCHAR(500)")
    op.execute("ALTER TABLE calendar_events ADD COLUMN IF NOT EXISTS is_all_day BOOLEAN NOT NULL DEFAULT false")


def downgrade():
    op.drop_column('calendar_events', 'is_all_day')
    op.drop_column('calendar_events', 'location')

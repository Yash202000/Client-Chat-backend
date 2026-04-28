"""add channel_id to calendar_events

Revision ID: r7s8t9u0v1w2
Revises: q6r7s8t9u0v1
Create Date: 2026-04-28
"""
from alembic import op
import sqlalchemy as sa

revision = 'r7s8t9u0v1w2'
down_revision = 'q6r7s8t9u0v1'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        ALTER TABLE calendar_events
        ADD COLUMN IF NOT EXISTS channel_id INTEGER REFERENCES chat_channels(id) ON DELETE SET NULL
    """)


def downgrade():
    op.execute("ALTER TABLE calendar_events DROP COLUMN IF EXISTS channel_id")

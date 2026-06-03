"""add email channel and subject to broadcasts

Revision ID: k6l7m8n9o0p1
Revises: j5k6l7m8n9o0
Create Date: 2026-05-23
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = 'k6l7m8n9o0p1'
down_revision = 'j5k6l7m8n9o0'
branch_labels = None
depends_on = None


def upgrade():
    # Add 'email' to the broadcastchannel enum
    op.execute("ALTER TYPE broadcastchannel ADD VALUE IF NOT EXISTS 'email'")

    # Add subject column to broadcasts (skip if already exists)
    conn = op.get_bind()
    cols = [c['name'] for c in inspect(conn).get_columns('broadcasts')]
    if 'subject' not in cols:
        op.add_column('broadcasts', sa.Column('subject', sa.String(500), nullable=True))


def downgrade():
    op.drop_column('broadcasts', 'subject')
    # Note: PostgreSQL does not support removing enum values; downgrade leaves the enum intact

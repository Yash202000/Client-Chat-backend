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
    conn = op.get_bind()

    # The enum may not exist if the table was bootstrapped via create_all rather than migrations.
    # Create it from scratch if missing; otherwise just add the new value.
    type_exists = conn.execute(
        sa.text("SELECT 1 FROM pg_type WHERE typname = 'broadcastchannel'")
    ).fetchone()

    if type_exists is None:
        op.execute("CREATE TYPE broadcastchannel AS ENUM ('whatsapp', 'sms', 'email')")
    else:
        op.execute("ALTER TYPE broadcastchannel ADD VALUE IF NOT EXISTS 'email'")

    # Add subject column to broadcasts (skip if already exists)
    cols = [c['name'] for c in inspect(conn).get_columns('broadcasts')]
    if 'subject' not in cols:
        op.add_column('broadcasts', sa.Column('subject', sa.String(500), nullable=True))


def downgrade():
    op.drop_column('broadcasts', 'subject')
    # Note: PostgreSQL does not support removing enum values; downgrade leaves the enum intact

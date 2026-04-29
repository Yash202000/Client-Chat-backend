"""add MEETING to channeltype enum

Revision ID: t9u0v1w2x3y4
Revises: s8t9u0v1w2x3
Create Date: 2026-04-29 00:00:00.000000
"""
from alembic import op

revision = 't9u0v1w2x3y4'
down_revision = 's8t9u0v1w2x3'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TYPE channeltype ADD VALUE IF NOT EXISTS 'MEETING'")


def downgrade():
    # Postgres does not support removing enum values; downgrade is a no-op
    pass

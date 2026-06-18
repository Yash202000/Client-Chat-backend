"""add twitter to social_platform enum

Revision ID: y0z1a2b3c4d5
Revises: x9y0z1a2b3c4
Create Date: 2026-06-12
"""
from alembic import op

revision = 'y0z1a2b3c4d5'
down_revision = 'x9y0z1a2b3c4'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TYPE socialplatform ADD VALUE IF NOT EXISTS 'twitter'")


def downgrade():
    # PostgreSQL does not support removing enum values
    pass

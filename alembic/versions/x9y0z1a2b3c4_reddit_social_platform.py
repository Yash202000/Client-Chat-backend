"""add reddit to social_platform enum and post_metadata to social_posts

Revision ID: x9y0z1a2b3c4
Revises: w8x9y0z1a2b3
Create Date: 2026-06-12
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'x9y0z1a2b3c4'
down_revision = 'w8x9y0z1a2b3'
branch_labels = None
depends_on = None


def upgrade():
    # Add 'reddit' to the socialplatform enum
    op.execute("ALTER TYPE socialplatform ADD VALUE IF NOT EXISTS 'reddit'")

    # Add post_metadata column to social_posts
    op.add_column('social_posts',
        sa.Column('post_metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=True)
    )


def downgrade():
    op.drop_column('social_posts', 'post_metadata')
    # Note: PostgreSQL does not support removing enum values — downgrade leaves enum intact

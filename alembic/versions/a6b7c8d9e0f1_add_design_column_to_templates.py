"""add design column to templates

Revision ID: a6b7c8d9e0f1
Revises: z5a6b7c8d9e0
Create Date: 2026-05-02

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'a6b7c8d9e0f1'
down_revision = 'z5a6b7c8d9e0'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('templates', sa.Column('design', postgresql.JSONB(), nullable=True))


def downgrade():
    op.drop_column('templates', 'design')

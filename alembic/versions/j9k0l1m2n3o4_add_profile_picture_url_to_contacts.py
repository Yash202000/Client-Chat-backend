"""add profile_picture_url to contacts

Revision ID: j9k0l1m2n3o4
Revises: i8j9k0l1m2n3
Create Date: 2026-04-26
"""
from alembic import op
import sqlalchemy as sa

revision = 'j9k0l1m2n3o4'
down_revision = 'fd40fd823124'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('contacts', sa.Column('profile_picture_url', sa.String(), nullable=True))


def downgrade():
    op.drop_column('contacts', 'profile_picture_url')

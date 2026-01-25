"""Add instance license table for on-premise deployments

Revision ID: i8j9k0l1m2n3
Revises: h7i8j9k0l1m2
Create Date: 2026-01-25

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'i8j9k0l1m2n3'
down_revision: Union[str, None] = 'h7i8j9k0l1m2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create instance_licenses table for on-premise licensing."""

    # Create instance_licenses table (singleton)
    op.create_table(
        'instance_licenses',
        sa.Column('id', sa.Integer(), nullable=False, default=1),
        sa.Column('license_key', sa.Text(), nullable=True),
        sa.Column('activated_at', sa.DateTime(), nullable=True),
        sa.Column('license_metadata', sa.JSON(), nullable=True),
        sa.Column('last_validated_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.CheckConstraint('id = 1', name='singleton_constraint'),
    )

    # Insert the singleton row
    op.execute("INSERT INTO instance_licenses (id) VALUES (1) ON CONFLICT DO NOTHING")


def downgrade() -> None:
    """Remove instance_licenses table."""
    op.drop_table('instance_licenses')

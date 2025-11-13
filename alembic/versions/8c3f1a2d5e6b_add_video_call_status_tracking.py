"""add_video_call_status_tracking

Revision ID: 8c3f1a2d5e6b
Revises: 5f8a2c1d9b3e
Create Date: 2025-11-13 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8c3f1a2d5e6b'
down_revision: Union[str, Sequence[str], None] = '5f8a2c1d9b3e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add new columns to video_calls table
    op.add_column('video_calls', sa.Column('invited_users', sa.JSON(), nullable=True))
    op.add_column('video_calls', sa.Column('joined_users', sa.JSON(), nullable=True))
    op.add_column('video_calls', sa.Column('answered_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('video_calls', sa.Column('timeout_seconds', sa.Integer(), nullable=False, server_default='30'))

    # Update status column default
    op.alter_column('video_calls', 'status',
                    existing_type=sa.String(),
                    server_default='ringing',
                    existing_nullable=True)


def downgrade() -> None:
    """Downgrade schema."""
    # Remove added columns
    op.drop_column('video_calls', 'timeout_seconds')
    op.drop_column('video_calls', 'answered_at')
    op.drop_column('video_calls', 'joined_users')
    op.drop_column('video_calls', 'invited_users')

    # Revert status column default
    op.alter_column('video_calls', 'status',
                    existing_type=sa.String(),
                    server_default='initiated',
                    existing_nullable=True)

"""add suggested_replies_enabled to notification_settings

Revision ID: 2ad70b10ae98
Revises: y0z1a2b3c4d5
Create Date: 2026-07-02 00:03:34.375642

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '2ad70b10ae98'
down_revision: Union[str, Sequence[str], None] = 'y0z1a2b3c4d5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'notification_settings',
        sa.Column('suggested_replies_enabled', sa.Boolean(), nullable=False, server_default=sa.true())
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('notification_settings', 'suggested_replies_enabled')

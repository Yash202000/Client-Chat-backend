"""add_is_client_connected_to_conversation_session

Revision ID: 0556b426cb06
Revises: a1b2c3d4e5f6
Create Date: 2025-10-17 11:47:12.265879

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0556b426cb06'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('conversation_sessions', sa.Column('is_client_connected', sa.Boolean(), nullable=False, server_default='false'))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('conversation_sessions', 'is_client_connected')

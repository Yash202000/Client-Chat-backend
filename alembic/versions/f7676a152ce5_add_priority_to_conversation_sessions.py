"""add_priority_to_conversation_sessions

Revision ID: f7676a152ce5
Revises: h3c4d5e6f7g8
Create Date: 2025-12-06 16:32:28.255773

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f7676a152ce5'
down_revision: Union[str, Sequence[str], None] = 'h3c4d5e6f7g8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add priority column with server_default for existing rows
    # 0=None, 1=Low, 2=Medium, 3=High, 4=Urgent
    op.add_column('conversation_sessions', sa.Column('priority', sa.Integer(), nullable=False, server_default='0'))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('conversation_sessions', 'priority')

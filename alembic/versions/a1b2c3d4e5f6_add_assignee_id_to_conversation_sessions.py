"""add assignee_id to conversation_sessions

Revision ID: a1b2c3d4e5f6
Revises: 99ae8eeabf0d
Create Date: 2025-10-16 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '99ae8eeabf0d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add assignee_id column to conversation_sessions table
    op.add_column('conversation_sessions', sa.Column('assignee_id', sa.Integer(), nullable=True))
    op.create_foreign_key(
        'conversation_sessions_assignee_id_fkey',
        'conversation_sessions',
        'users',
        ['assignee_id'],
        ['id']
    )


def downgrade() -> None:
    """Downgrade schema."""
    # Remove foreign key and column
    op.drop_constraint('conversation_sessions_assignee_id_fkey', 'conversation_sessions', type_='foreignkey')
    op.drop_column('conversation_sessions', 'assignee_id')

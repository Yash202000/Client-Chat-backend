"""add_subworkflow_stack_to_conversation_sessions

Revision ID: a1b2c3d4e5f6
Revises: 93c70d915e2c
Create Date: 2025-12-19

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSON

# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '93c70d915e2c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add subworkflow_stack column to conversation_sessions."""
    op.add_column('conversation_sessions', sa.Column('subworkflow_stack', JSON, nullable=True))


def downgrade() -> None:
    """Remove subworkflow_stack column from conversation_sessions."""
    op.drop_column('conversation_sessions', 'subworkflow_stack')

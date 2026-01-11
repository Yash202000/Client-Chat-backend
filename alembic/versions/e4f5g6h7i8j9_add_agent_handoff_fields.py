"""Add agent-to-agent handoff fields

Revision ID: e4f5g6h7i8j9
Revises: d3e4f5g6h7i8
Create Date: 2026-01-11

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSON


# revision identifiers, used by Alembic.
revision: str = 'e4f5g6h7i8j9'
down_revision: Union[str, None] = 'd3e4f5g6h7i8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add agent specialization and handoff config to agents table
    op.add_column('agents', sa.Column('specialization_topics', JSON, nullable=True))
    op.add_column('agents', sa.Column('handoff_config', JSON, nullable=True))

    # Add agent transition tracking to conversation_sessions table
    op.add_column('conversation_sessions', sa.Column('original_agent_id', sa.Integer(), sa.ForeignKey('agents.id'), nullable=True))
    op.add_column('conversation_sessions', sa.Column('previous_agent_id', sa.Integer(), sa.ForeignKey('agents.id'), nullable=True))
    op.add_column('conversation_sessions', sa.Column('agent_transition_history', JSON, nullable=True))
    op.add_column('conversation_sessions', sa.Column('handoff_summary', sa.Text(), nullable=True))


def downgrade() -> None:
    # Remove agent transition tracking from conversation_sessions
    op.drop_column('conversation_sessions', 'handoff_summary')
    op.drop_column('conversation_sessions', 'agent_transition_history')
    op.drop_column('conversation_sessions', 'previous_agent_id')
    op.drop_column('conversation_sessions', 'original_agent_id')

    # Remove agent specialization and handoff config from agents
    op.drop_column('agents', 'handoff_config')
    op.drop_column('agents', 'specialization_topics')

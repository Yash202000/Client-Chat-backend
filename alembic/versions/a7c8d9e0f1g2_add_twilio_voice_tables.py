"""add_twilio_voice_tables

Revision ID: a7c8d9e0f1g2
Revises: 5bc261b566b8
Create Date: 2025-12-29 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'a7c8d9e0f1g2'
down_revision: Union[str, Sequence[str], None] = '5bc261b566b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Create voice_calls table
    op.create_table(
        'voice_calls',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('call_sid', sa.String(), nullable=False),
        sa.Column('stream_sid', sa.String(), nullable=True),
        sa.Column('from_number', sa.String(), nullable=False),
        sa.Column('to_number', sa.String(), nullable=False),
        sa.Column('company_id', sa.Integer(), nullable=False),
        sa.Column('agent_id', sa.Integer(), nullable=True),
        sa.Column('integration_id', sa.Integer(), nullable=True),
        sa.Column('conversation_id', sa.String(), nullable=True),
        sa.Column('contact_id', sa.Integer(), nullable=True),
        sa.Column('status', sa.String(), nullable=True),
        sa.Column('direction', sa.String(), nullable=True),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('answered_at', sa.DateTime(), nullable=True),
        sa.Column('ended_at', sa.DateTime(), nullable=True),
        sa.Column('duration_seconds', sa.Float(), nullable=True),
        sa.Column('full_transcript', sa.Text(), nullable=True),
        sa.Column('call_metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ),
        sa.ForeignKeyConstraint(['agent_id'], ['agents.id'], ),
        sa.ForeignKeyConstraint(['integration_id'], ['integrations.id'], ),
        sa.ForeignKeyConstraint(['conversation_id'], ['conversation_sessions.conversation_id'], ),
        sa.ForeignKeyConstraint(['contact_id'], ['contacts.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_voice_calls_id'), 'voice_calls', ['id'], unique=False)
    op.create_index(op.f('ix_voice_calls_call_sid'), 'voice_calls', ['call_sid'], unique=True)
    op.create_index(op.f('ix_voice_calls_stream_sid'), 'voice_calls', ['stream_sid'], unique=True)

    # Create twilio_phone_numbers table
    op.create_table(
        'twilio_phone_numbers',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('phone_number', sa.String(), nullable=False),
        sa.Column('friendly_name', sa.String(), nullable=True),
        sa.Column('company_id', sa.Integer(), nullable=False),
        sa.Column('default_agent_id', sa.Integer(), nullable=True),
        sa.Column('integration_id', sa.Integer(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=True),
        sa.Column('welcome_message', sa.String(), nullable=True),
        sa.Column('language', sa.String(), nullable=True),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ),
        sa.ForeignKeyConstraint(['default_agent_id'], ['agents.id'], ),
        sa.ForeignKeyConstraint(['integration_id'], ['integrations.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_twilio_phone_numbers_id'), 'twilio_phone_numbers', ['id'], unique=False)
    op.create_index(op.f('ix_twilio_phone_numbers_phone_number'), 'twilio_phone_numbers', ['phone_number'], unique=True)


def downgrade() -> None:
    """Downgrade schema."""
    # Drop twilio_phone_numbers table
    op.drop_index(op.f('ix_twilio_phone_numbers_phone_number'), table_name='twilio_phone_numbers')
    op.drop_index(op.f('ix_twilio_phone_numbers_id'), table_name='twilio_phone_numbers')
    op.drop_table('twilio_phone_numbers')

    # Drop voice_calls table
    op.drop_index(op.f('ix_voice_calls_stream_sid'), table_name='voice_calls')
    op.drop_index(op.f('ix_voice_calls_call_sid'), table_name='voice_calls')
    op.drop_index(op.f('ix_voice_calls_id'), table_name='voice_calls')
    op.drop_table('voice_calls')

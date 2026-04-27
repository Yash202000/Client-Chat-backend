"""add call recording fields and call queue table

Revision ID: k0l1m2n3o4p5
Revises: j9k0l1m2n3o4
Create Date: 2026-04-26
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = 'k0l1m2n3o4p5'
down_revision = 'j9k0l1m2n3o4'
branch_labels = None
depends_on = None


def upgrade():
    # Add recording columns to voice_calls
    op.add_column('voice_calls', sa.Column('recording_url', sa.String(), nullable=True))
    op.add_column('voice_calls', sa.Column('recording_duration_secs', sa.Float(), nullable=True))

    # call_queue_entries may already exist — create only if missing
    from sqlalchemy import inspect as sa_inspect
    from alembic import op as _op
    bind = _op.get_bind()
    if 'call_queue_entries' not in sa_inspect(bind).get_table_names():
        op.create_table(
        'call_queue_entries',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('company_id', sa.Integer(), sa.ForeignKey('companies.id'), nullable=False),
        sa.Column('call_sid', sa.String(), nullable=False, index=True),
        sa.Column('source', sa.String(), nullable=False, server_default='twilio'),
        sa.Column('caller_number', sa.String(), nullable=False),
        sa.Column('caller_name', sa.String(), nullable=True),
        sa.Column('session_id', sa.String(), sa.ForeignKey('conversation_sessions.conversation_id'), nullable=True),
        sa.Column('contact_id', sa.Integer(), sa.ForeignKey('contacts.id'), nullable=True),
        sa.Column('status', sa.String(), nullable=False, server_default='waiting', index=True),
        sa.Column('priority', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('entered_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('ringing_at', sa.DateTime(), nullable=True),
        sa.Column('connected_at', sa.DateTime(), nullable=True),
        sa.Column('ended_at', sa.DateTime(), nullable=True),
        sa.Column('estimated_wait_secs', sa.Integer(), nullable=True),
        sa.Column('assigned_agent_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('extra', JSONB(), nullable=True),
    )


def downgrade():
    op.drop_table('call_queue_entries')
    op.drop_column('voice_calls', 'recording_duration_secs')
    op.drop_column('voice_calls', 'recording_url')

"""contact centre M3: queues, agent states, reason/disposition codes, shifts, extensions, directory

Revision ID: c3q4u5e6u7e8
Revises: b2c3a4l5l6s7
Create Date: 2026-10-13 00:00:02

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'c3q4u5e6u7e8'
down_revision: Union[str, Sequence[str], None] = 'b2c3a4l5l6s7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

JSONB = postgresql.JSONB


def _tables(conn):
    return set(sa.inspect(conn).get_table_names())


def _columns(conn, table):
    return {c['name'] for c in sa.inspect(conn).get_columns(table)}


def upgrade() -> None:
    conn = op.get_bind()
    tables = _tables(conn)  # app.main create_all may have created some already on a running dev server

    if 'agent_reason_codes' not in tables:
        op.create_table(
            'agent_reason_codes',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('company_id', sa.Integer(), sa.ForeignKey('companies.id'), nullable=False, index=True),
            sa.Column('name', sa.String(64), nullable=False),
            sa.Column('state', sa.String(16), nullable=False, server_default='break'),
            sa.Column('allowed_role_ids', JSONB(), nullable=True),
            sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        )
    if 'call_disposition_codes' not in tables:
        op.create_table(
            'call_disposition_codes',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('company_id', sa.Integer(), sa.ForeignKey('companies.id'), nullable=False, index=True),
            sa.Column('name', sa.String(64), nullable=False),
            sa.Column('requires_note', sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        )
    if 'call_queues' not in tables:
        op.create_table(
            'call_queues',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('company_id', sa.Integer(), sa.ForeignKey('companies.id'), nullable=False, index=True),
            sa.Column('name', sa.String(128), nullable=False),
            sa.Column('description', sa.String(512), nullable=True),
            sa.Column('priority', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('required_skill', sa.String(64), nullable=True),
            sa.Column('is_open', sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column('is_supervisor_queue', sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column('offer_timeout_seconds', sa.Integer(), nullable=False, server_default='20'),
            sa.Column('max_wait_seconds', sa.Integer(), nullable=False, server_default='120'),
            sa.Column('overflow_text', sa.Text(), nullable=True),
            sa.Column('wrap_up_seconds', sa.Integer(), nullable=False, server_default='30'),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.UniqueConstraint('company_id', 'name', name='uq_call_queues_company_name'),
        )
    if 'call_queue_members' not in tables:
        op.create_table(
            'call_queue_members',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('queue_id', sa.Integer(), sa.ForeignKey('call_queues.id', ondelete='CASCADE'), nullable=False, index=True),
            sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True),
            sa.Column('tier', sa.Integer(), nullable=False, server_default='1'),
            sa.UniqueConstraint('queue_id', 'user_id', name='uq_call_queue_members'),
        )
    if 'agent_states' not in tables:
        op.create_table(
            'agent_states',
            sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), primary_key=True),
            sa.Column('company_id', sa.Integer(), sa.ForeignKey('companies.id'), nullable=False, index=True),
            sa.Column('state', sa.String(16), nullable=False, server_default='logged_out'),
            sa.Column('reason_code_id', sa.Integer(), sa.ForeignKey('agent_reason_codes.id', ondelete='SET NULL'), nullable=True),
            sa.Column('since', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column('last_call_ended_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('current_call_id', sa.Integer(), sa.ForeignKey('voice_calls.id', ondelete='SET NULL'), nullable=True),
        )
    if 'agent_state_history' not in tables:
        op.create_table(
            'agent_state_history',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True),
            sa.Column('company_id', sa.Integer(), sa.ForeignKey('companies.id'), nullable=False, index=True),
            sa.Column('state', sa.String(16), nullable=False),
            sa.Column('reason_code_id', sa.Integer(), sa.ForeignKey('agent_reason_codes.id', ondelete='SET NULL'), nullable=True),
            sa.Column('started_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column('ended_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('changed_by_user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
            sa.Column('source', sa.String(16), nullable=False, server_default='manual'),
        )
    if 'agent_shifts' not in tables:
        op.create_table(
            'agent_shifts',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('company_id', sa.Integer(), sa.ForeignKey('companies.id'), nullable=False, index=True),
            sa.Column('name', sa.String(64), nullable=False),
            sa.Column('timezone', sa.String(64), nullable=False, server_default='Asia/Riyadh'),
            sa.Column('schedule', JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
            sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        )
    if 'agent_shift_assignments' not in tables:
        op.create_table(
            'agent_shift_assignments',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('shift_id', sa.Integer(), sa.ForeignKey('agent_shifts.id', ondelete='CASCADE'), nullable=False, index=True),
            sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True),
            sa.Column('role', sa.String(16), nullable=False, server_default='agent'),
            sa.UniqueConstraint('shift_id', 'user_id', name='uq_agent_shift_assignments'),
        )
    if 'user_extensions' not in tables:
        op.create_table(
            'user_extensions',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('company_id', sa.Integer(), sa.ForeignKey('companies.id'), nullable=False, index=True),
            sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, unique=True),
            sa.Column('extension', sa.String(16), nullable=False),
            sa.UniqueConstraint('company_id', 'extension', name='uq_user_extensions_company_ext'),
        )
    if 'phone_directory_entries' not in tables:
        op.create_table(
            'phone_directory_entries',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('company_id', sa.Integer(), sa.ForeignKey('companies.id'), nullable=False, index=True),
            sa.Column('name', sa.String(128), nullable=False),
            sa.Column('number', sa.String(32), nullable=False),
            sa.Column('kind', sa.String(16), nullable=False, server_default='external'),
            sa.Column('transfer_allowed', sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column('notes', sa.String(255), nullable=True),
        )

    # Queue entries: link to the call, queue and the agent currently being offered the call
    cols = _columns(conn, 'call_queue_entries')
    for col in [
        sa.Column('queue_id', sa.Integer(), sa.ForeignKey('call_queues.id', ondelete='SET NULL'), nullable=True),
        sa.Column('voice_call_id', sa.Integer(), sa.ForeignKey('voice_calls.id', ondelete='CASCADE'), nullable=True),
        sa.Column('offered_to_user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('offer_expires_at', sa.DateTime(), nullable=True),
        sa.Column('offer_attempts', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('declined_user_ids', JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
    ]:
        if col.name not in cols:
            op.add_column('call_queue_entries', col)

    cols = _columns(conn, 'voice_calls')
    for col in [
        sa.Column('queue_id', sa.Integer(), sa.ForeignKey('call_queues.id', ondelete='SET NULL'), nullable=True),
        sa.Column('disposition_code_id', sa.Integer(), sa.ForeignKey('call_disposition_codes.id', ondelete='SET NULL'), nullable=True),
        sa.Column('disposition_note', sa.Text(), nullable=True),
        sa.Column('hold_started_at', sa.DateTime(), nullable=True),
        sa.Column('manual_entry', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('reconciled_with_call_id', sa.Integer(), sa.ForeignKey('voice_calls.id', ondelete='SET NULL'), nullable=True),
    ]:
        if col.name not in cols:
            op.add_column('voice_calls', col)

    cols = _columns(conn, 'phone_numbers')
    if 'queue_id' not in cols:
        op.add_column('phone_numbers', sa.Column('queue_id', sa.Integer(), sa.ForeignKey('call_queues.id', ondelete='SET NULL'), nullable=True))


def downgrade() -> None:
    op.drop_column('phone_numbers', 'queue_id')
    for name in ['reconciled_with_call_id', 'manual_entry', 'hold_started_at', 'disposition_note', 'disposition_code_id', 'queue_id']:
        op.drop_column('voice_calls', name)
    for name in ['declined_user_ids', 'offer_attempts', 'offer_expires_at', 'offered_to_user_id', 'voice_call_id', 'queue_id']:
        op.drop_column('call_queue_entries', name)
    for table in ['phone_directory_entries', 'user_extensions', 'agent_shift_assignments', 'agent_shifts',
                  'agent_state_history', 'agent_states', 'call_queue_members', 'call_queues',
                  'call_disposition_codes', 'agent_reason_codes']:
        op.drop_table(table)

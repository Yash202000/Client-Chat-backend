"""contact centre M5: settings, missed-call tasks + callback attempts, blocklist, call purposes, outbound fields

Revision ID: e5m6i7s8s9e0
Revises: d4t5r6a7n8s9
Create Date: 2026-10-13 00:00:04

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'e5m6i7s8s9e0'
down_revision: Union[str, Sequence[str], None] = 'd4t5r6a7n8s9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    tables = set(sa.inspect(conn).get_table_names())
    if 'contact_center_settings' not in tables:
        op.create_table(
            'contact_center_settings',
            sa.Column('company_id', sa.Integer(), sa.ForeignKey('companies.id'), primary_key=True),
            sa.Column('abandon_threshold_seconds', sa.Integer(), nullable=False, server_default='5'),
            sa.Column('create_callback_tasks', sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column('default_country_code', sa.String(8), nullable=False, server_default='+966'),
            sa.Column('allowed_country_codes', postgresql.JSONB(), nullable=False, server_default=sa.text('\'["+966"]\'::jsonb')),
            sa.Column('outbound_caller_number', sa.String(32), nullable=True),
            sa.Column('outbound_trunk_address', sa.String(255), nullable=True),
            sa.Column('outbound_auth_username', sa.String(128), nullable=True),
            sa.Column('outbound_auth_password', sa.String(255), nullable=True),
            sa.Column('outbound_trunk_id', sa.String(64), nullable=True),
            sa.Column('refusal_comment_required', sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
    if 'number_blocklist' not in tables:
        op.create_table(
            'number_blocklist',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('company_id', sa.Integer(), sa.ForeignKey('companies.id'), nullable=False, index=True),
            sa.Column('number', sa.String(32), nullable=False),
            sa.Column('scope', sa.String(16), nullable=False, server_default='outbound'),  # outbound | inbound | both
            sa.Column('reason', sa.String(255), nullable=True),
            sa.Column('created_by_user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.UniqueConstraint('company_id', 'number', name='uq_number_blocklist'),
        )
    if 'call_purpose_codes' not in tables:
        op.create_table(
            'call_purpose_codes',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('company_id', sa.Integer(), sa.ForeignKey('companies.id'), nullable=False, index=True),
            sa.Column('name', sa.String(64), nullable=False),
            sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        )
    if 'missed_call_tasks' not in tables:
        op.create_table(
            'missed_call_tasks',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('company_id', sa.Integer(), sa.ForeignKey('companies.id'), nullable=False, index=True),
            sa.Column('call_id', sa.Integer(), sa.ForeignKey('voice_calls.id', ondelete='CASCADE'), nullable=False, unique=True),
            sa.Column('caller_number', sa.String(32), nullable=False, index=True),
            sa.Column('contact_id', sa.Integer(), sa.ForeignKey('contacts.id', ondelete='SET NULL'), nullable=True),
            sa.Column('queue_id', sa.Integer(), sa.ForeignKey('call_queues.id', ondelete='SET NULL'), nullable=True),
            sa.Column('classification', sa.String(16), nullable=False),  # missed | abandoned
            sa.Column('loss_reason', sa.String(48), nullable=True),
            sa.Column('wait_seconds', sa.Float(), nullable=True),
            sa.Column('status', sa.String(16), nullable=False, server_default='open'),  # open | assigned | closed
            sa.Column('assigned_to_user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True, index=True),
            sa.Column('assigned_by_user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
            sa.Column('assigned_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('result', sa.String(24), nullable=True),  # answered | no_answer | invalid_number | refused | resolved_elsewhere
            sa.Column('result_comment', sa.Text(), nullable=True),
            sa.Column('closed_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('closed_by_user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
            sa.Column('attempts', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
    if 'callback_attempts' not in tables:
        op.create_table(
            'callback_attempts',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('task_id', sa.Integer(), sa.ForeignKey('missed_call_tasks.id', ondelete='CASCADE'), nullable=False, index=True),
            sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
            sa.Column('voice_call_id', sa.Integer(), sa.ForeignKey('voice_calls.id', ondelete='SET NULL'), nullable=True),
            sa.Column('started_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column('ended_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('result', sa.String(24), nullable=True),
            sa.Column('duration_seconds', sa.Float(), nullable=True),
        )
    cols = {c['name'] for c in sa.inspect(conn).get_columns('voice_calls')}
    for col in [
        sa.Column('call_purpose_id', sa.Integer(), sa.ForeignKey('call_purpose_codes.id', ondelete='SET NULL'), nullable=True),
        sa.Column('outbound_result', sa.String(24), nullable=True),  # answered | no_answer | busy | invalid_number | failed | refused
        sa.Column('missed_classification', sa.String(16), nullable=True),  # missed | abandoned | short_abandon
    ]:
        if col.name not in cols:
            op.add_column('voice_calls', col)


def downgrade() -> None:
    for name in ['missed_classification', 'outbound_result', 'call_purpose_id']:
        op.drop_column('voice_calls', name)
    for table in ['callback_attempts', 'missed_call_tasks', 'call_purpose_codes', 'number_blocklist', 'contact_center_settings']:
        op.drop_table(table)

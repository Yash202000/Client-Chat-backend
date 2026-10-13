"""contact centre calls: provider-neutral voice_calls columns, call_events, number routing mode (M1a)

Revision ID: b2c3a4l5l6s7
Revises: a1t2e3l4e5p6
Create Date: 2026-10-13 00:00:01

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'b2c3a4l5l6s7'
down_revision: Union[str, Sequence[str], None] = 'a1t2e3l4e5p6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

VOICE_CALL_COLUMNS = [
    sa.Column('provider', sa.String(32), nullable=False, server_default='twilio'),
    sa.Column('room_name', sa.String(128), nullable=True),
    sa.Column('phone_number_id', sa.Integer(), sa.ForeignKey('phone_numbers.id', ondelete='SET NULL'), nullable=True),
    sa.Column('handled_by_user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
    sa.Column('ended_by', sa.String(32), nullable=True),
    sa.Column('talk_seconds', sa.Float(), nullable=True),
    sa.Column('hold_seconds', sa.Float(), nullable=False, server_default='0'),
    sa.Column('wrap_up_seconds', sa.Float(), nullable=True),
]

PHONE_NUMBER_COLUMNS = [
    # "ai": voice process answers (entry workflow / AI agent). "direct": ring human agents' browsers.
    sa.Column('routing_mode', sa.String(16), nullable=False, server_default='ai'),
    sa.Column('ring_team_id', sa.Integer(), sa.ForeignKey('teams.id', ondelete='SET NULL'), nullable=True),
]


def _columns(conn, table):
    return {c['name'] for c in sa.inspect(conn).get_columns(table)}


def upgrade() -> None:
    """Upgrade schema."""
    conn = op.get_bind()

    existing = _columns(conn, 'voice_calls')
    for col in VOICE_CALL_COLUMNS:
        if col.name not in existing:
            op.add_column('voice_calls', col.copy())
    indexes = {i['name'] for i in sa.inspect(conn).get_indexes('voice_calls')}
    if 'ix_voice_calls_room_name' not in indexes:
        op.create_index('ix_voice_calls_room_name', 'voice_calls', ['room_name'])

    existing = _columns(conn, 'phone_numbers')
    for col in PHONE_NUMBER_COLUMNS:
        if col.name not in existing:
            op.add_column('phone_numbers', col.copy())

    # app.main runs Base.metadata.create_all, so a running dev server may already have created it
    if 'call_events' not in sa.inspect(conn).get_table_names():
        op.create_table(
            'call_events',
            sa.Column('id', sa.BigInteger(), primary_key=True),
            sa.Column('call_id', sa.Integer(), sa.ForeignKey('voice_calls.id', ondelete='CASCADE'), nullable=False),
            sa.Column('seq', sa.Integer(), nullable=False),
            sa.Column('type', sa.String(48), nullable=False),
            sa.Column('at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column('actor_type', sa.String(16), nullable=False, server_default='system'),
            sa.Column('actor_user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
            sa.Column('payload', postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
            sa.UniqueConstraint('call_id', 'seq', name='uq_call_events_call_seq'),
        )
        op.create_index('ix_call_events_call_id', 'call_events', ['call_id'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_call_events_call_id', table_name='call_events')
    op.drop_table('call_events')
    for col in PHONE_NUMBER_COLUMNS:
        op.drop_column('phone_numbers', col.name)
    op.drop_index('ix_voice_calls_room_name', table_name='voice_calls')
    for col in VOICE_CALL_COLUMNS:
        op.drop_column('voice_calls', col.name)

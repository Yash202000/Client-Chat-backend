"""contact centre M4: call legs (transfer chain), recording + quality fields, supervision/recording permissions

Revision ID: d4t5r6a7n8s9
Revises: c3q4u5e6u7e8
Create Date: 2026-10-13 00:00:03

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'd4t5r6a7n8s9'
down_revision: Union[str, Sequence[str], None] = 'c3q4u5e6u7e8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PERMISSIONS = {
    "calls:supervise": "Listen to, whisper to or join agents' live calls",
    "recordings:listen": "Play call recordings",
    "recordings:download": "Download call recordings",
}


def upgrade() -> None:
    conn = op.get_bind()
    if 'call_legs' not in sa.inspect(conn).get_table_names():
        op.create_table(
            'call_legs',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('call_id', sa.Integer(), sa.ForeignKey('voice_calls.id', ondelete='CASCADE'), nullable=False, index=True),
            sa.Column('seq', sa.Integer(), nullable=False),
            sa.Column('kind', sa.String(16), nullable=False),  # ai | agent | consult | supervisor | external
            sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
            sa.Column('party', sa.String(128), nullable=True),
            sa.Column('started_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column('ended_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('end_reason', sa.String(32), nullable=True),  # transferred | hung_up | caller_hung_up | left
            sa.Column('transferred_to', sa.String(128), nullable=True),
            sa.UniqueConstraint('call_id', 'seq', name='uq_call_legs_call_seq'),
        )
    cols = {c['name'] for c in sa.inspect(conn).get_columns('voice_calls')}
    for col in [
        sa.Column('recording_status', sa.String(16), nullable=True),  # recording | completed | failed
        sa.Column('recording_started_at', sa.DateTime(), nullable=True),
        sa.Column('recording_ended_at', sa.DateTime(), nullable=True),
        sa.Column('recording_egress_id', sa.String(64), nullable=True),
        sa.Column('recording_object_key', sa.String(512), nullable=True),
        sa.Column('quality', postgresql.JSONB(), nullable=True),
    ]:
        if col.name not in cols:
            op.add_column('voice_calls', col)

    for name, desc in PERMISSIONS.items():
        conn.execute(sa.text("INSERT INTO permissions (name, description) SELECT :n, :d "
                             "WHERE NOT EXISTS (SELECT 1 FROM permissions WHERE name = :n)"), {"n": name, "d": desc})
        conn.execute(sa.text("INSERT INTO role_permissions (role_id, permission_id) "
                             "SELECT r.id, p.id FROM roles r JOIN permissions p ON p.name = :n "
                             "WHERE r.name IN ('Admin', 'Super Admin') AND NOT EXISTS "
                             "(SELECT 1 FROM role_permissions rp WHERE rp.role_id = r.id AND rp.permission_id = p.id)"),
                     {"n": name})


def downgrade() -> None:
    conn = op.get_bind()
    for name in PERMISSIONS:
        conn.execute(sa.text("DELETE FROM role_permissions WHERE permission_id IN (SELECT id FROM permissions WHERE name = :n)"), {"n": name})
        conn.execute(sa.text("DELETE FROM permissions WHERE name = :n"), {"n": name})
    for name in ['quality', 'recording_object_key', 'recording_egress_id', 'recording_ended_at', 'recording_started_at', 'recording_status']:
        op.drop_column('voice_calls', name)
    op.drop_table('call_legs')

"""Wait time announcement per queue (FR-CC-013) and recording pause / parts (FR-CC-051)

Revision ID: i9w0a1i2t3r4
Revises: h8p9e0r1m2s3
Create Date: 2026-10-14 00:00:01

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'i9w0a1i2t3r4'
down_revision: Union[str, Sequence[str], None] = 'h8p9e0r1m2s3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PERMISSION = ("recordings:pause", "Pause and resume the recording of a call (e.g. while card details are given)")


def _has(conn, table, column):
    return column in {c["name"] for c in sa.inspect(conn).get_columns(table)}


def upgrade() -> None:
    conn = op.get_bind()
    if not _has(conn, 'call_queues', 'announce_wait_time'):
        op.add_column('call_queues', sa.Column('announce_wait_time', sa.Boolean(), nullable=False, server_default=sa.false()))
    if not _has(conn, 'call_queues', 'announce_interval_seconds'):
        op.add_column('call_queues', sa.Column('announce_interval_seconds', sa.Integer(), nullable=False, server_default='60'))
    if not _has(conn, 'voice_calls', 'recording_parts'):
        op.add_column('voice_calls', sa.Column('recording_parts', postgresql.JSONB(), nullable=False,
                                               server_default=sa.text("'[]'::jsonb")))
    if not _has(conn, 'voice_calls', 'recording_paused_at'):
        op.add_column('voice_calls', sa.Column('recording_paused_at', sa.DateTime(), nullable=True))
    # existing recordings become one-part recordings
    conn.execute(sa.text(
        "UPDATE voice_calls SET recording_parts = jsonb_build_array(jsonb_build_object("
        "'egress_id', recording_egress_id, 'key', recording_object_key, 'status', recording_status, "
        "'duration', recording_duration_secs)) "
        "WHERE recording_egress_id IS NOT NULL AND recording_parts = '[]'::jsonb"))
    name, desc = PERMISSION
    conn.execute(sa.text("INSERT INTO permissions (name, description) SELECT :n, :d "
                         "WHERE NOT EXISTS (SELECT 1 FROM permissions WHERE name = :n)"), {"n": name, "d": desc})
    conn.execute(sa.text("INSERT INTO role_permissions (role_id, permission_id) "
                         "SELECT r.id, p.id FROM roles r JOIN permissions p ON p.name = :n "
                         "WHERE r.name IN ('Admin', 'Super Admin') "
                         "AND NOT EXISTS (SELECT 1 FROM role_permissions rp WHERE rp.role_id = r.id AND rp.permission_id = p.id)"),
                 {"n": name})


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("DELETE FROM role_permissions WHERE permission_id IN (SELECT id FROM permissions WHERE name = :n)"),
                 {"n": PERMISSION[0]})
    conn.execute(sa.text("DELETE FROM permissions WHERE name = :n"), {"n": PERMISSION[0]})
    op.drop_column('voice_calls', 'recording_paused_at')
    op.drop_column('voice_calls', 'recording_parts')
    op.drop_column('call_queues', 'announce_interval_seconds')
    op.drop_column('call_queues', 'announce_wait_time')

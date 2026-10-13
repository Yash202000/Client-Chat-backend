"""contact centre M6: QA forms + evaluations, data retention settings

Revision ID: f6r7e8p9o0r1
Revises: e5m6i7s8s9e0
Create Date: 2026-10-13 00:00:05

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'f6r7e8p9o0r1'
down_revision: Union[str, Sequence[str], None] = 'e5m6i7s8s9e0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PERMISSIONS = {
    "calls:evaluate": "Evaluate call quality (QA forms and evaluations)",
    "reports:export": "Export contact-centre reports",
}


def upgrade() -> None:
    conn = op.get_bind()
    tables = set(sa.inspect(conn).get_table_names())
    if 'qa_forms' not in tables:
        op.create_table(
            'qa_forms',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('company_id', sa.Integer(), sa.ForeignKey('companies.id'), nullable=False, index=True),
            sa.Column('name', sa.String(128), nullable=False),
            # [{"key": "greeting", "label": "Greeted the caller", "weight": 10}, ...]
            sa.Column('criteria', postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
            sa.Column('pass_score', sa.Integer(), nullable=False, server_default='70'),
            sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
    if 'qa_evaluations' not in tables:
        op.create_table(
            'qa_evaluations',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('company_id', sa.Integer(), sa.ForeignKey('companies.id'), nullable=False, index=True),
            sa.Column('form_id', sa.Integer(), sa.ForeignKey('qa_forms.id', ondelete='SET NULL'), nullable=True),
            sa.Column('call_id', sa.Integer(), sa.ForeignKey('voice_calls.id', ondelete='CASCADE'), nullable=False, index=True),
            sa.Column('agent_user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True, index=True),
            sa.Column('evaluator_user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
            sa.Column('status', sa.String(16), nullable=False, server_default='pending'),  # pending | completed
            sa.Column('scores', postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
            sa.Column('total_score', sa.Float(), nullable=True),
            sa.Column('passed', sa.Boolean(), nullable=True),
            sa.Column('notes', sa.Text(), nullable=True),
            sa.Column('improvement_plan', sa.Text(), nullable=True),
            sa.Column('sample_batch', sa.String(32), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        )
    cols = {c['name'] for c in sa.inspect(conn).get_columns('contact_center_settings')}
    for col in [
        sa.Column('recording_retention_days', sa.Integer(), nullable=True),   # null = keep for life
        sa.Column('call_history_retention_days', sa.Integer(), nullable=True),
        sa.Column('chat_retention_days', sa.Integer(), nullable=True),
        sa.Column('retention_changed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('service_level_seconds', sa.Integer(), nullable=False, server_default='20'),
    ]:
        if col.name not in cols:
            op.add_column('contact_center_settings', col)
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
    for name in ['service_level_seconds', 'retention_changed_at', 'chat_retention_days', 'call_history_retention_days', 'recording_retention_days']:
        op.drop_column('contact_center_settings', name)
    op.drop_table('qa_evaluations')
    op.drop_table('qa_forms')

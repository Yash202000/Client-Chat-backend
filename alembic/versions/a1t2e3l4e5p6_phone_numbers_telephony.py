"""phone_numbers table and telephony permissions (LiveKit SIP contact centre, M0)

Revision ID: a1t2e3l4e5p6
Revises: 2ad70b10ae98
Create Date: 2026-10-13 00:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'a1t2e3l4e5p6'
down_revision: Union[str, Sequence[str], None] = '2ad70b10ae98'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TELEPHONY_PERMISSIONS = {
    "telephony:read": "View phone numbers and telephony settings",
    "telephony:manage": "Manage phone numbers, trunks and telephony settings",
}


def upgrade() -> None:
    """Upgrade schema."""
    conn = op.get_bind()
    # app.main runs Base.metadata.create_all, so a running dev server may already have created the table
    if 'phone_numbers' not in sa.inspect(conn).get_table_names():
        _create_phone_numbers()
    _grant_permissions(conn)


def _create_phone_numbers() -> None:
    op.create_table(
        'phone_numbers',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('company_id', sa.Integer(), sa.ForeignKey('companies.id'), nullable=False),
        sa.Column('number', sa.String(32), nullable=False),
        sa.Column('friendly_name', sa.String(255), nullable=True),
        sa.Column('provider', sa.String(32), nullable=False, server_default='livekit_sip'),
        sa.Column('entry_workflow_id', sa.Integer(), sa.ForeignKey('workflows.id', ondelete='SET NULL'), nullable=True),
        sa.Column('default_agent_id', sa.Integer(), sa.ForeignKey('agents.id', ondelete='SET NULL'), nullable=True),
        sa.Column('language', sa.String(16), nullable=False, server_default='en'),
        sa.Column('recording_enabled', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('provider_config', postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint('provider', 'number', name='uq_phone_numbers_provider_number'),
    )
    op.create_index('ix_phone_numbers_id', 'phone_numbers', ['id'])
    op.create_index('ix_phone_numbers_company_id', 'phone_numbers', ['company_id'])
    op.create_index('ix_phone_numbers_number', 'phone_numbers', ['number'])


def _grant_permissions(conn) -> None:
    # Permissions are normally created at app startup; create them here too so existing
    # company Admin roles can be granted them (startup only updates Super Admin).
    for name, desc in TELEPHONY_PERMISSIONS.items():
        conn.execute(
            sa.text("INSERT INTO permissions (name, description) SELECT :n, :d "
                    "WHERE NOT EXISTS (SELECT 1 FROM permissions WHERE name = :n)"),
            {"n": name, "d": desc},
        )
        conn.execute(
            sa.text("INSERT INTO role_permissions (role_id, permission_id) "
                    "SELECT r.id, p.id FROM roles r JOIN permissions p ON p.name = :n "
                    "WHERE r.name IN ('Admin', 'Super Admin') "
                    "AND NOT EXISTS (SELECT 1 FROM role_permissions rp WHERE rp.role_id = r.id AND rp.permission_id = p.id)"),
            {"n": name},
        )


def downgrade() -> None:
    """Downgrade schema."""
    conn = op.get_bind()
    for name in TELEPHONY_PERMISSIONS:
        conn.execute(sa.text("DELETE FROM role_permissions WHERE permission_id IN (SELECT id FROM permissions WHERE name = :n)"), {"n": name})
        conn.execute(sa.text("DELETE FROM permissions WHERE name = :n"), {"n": name})
    op.drop_index('ix_phone_numbers_number', table_name='phone_numbers')
    op.drop_index('ix_phone_numbers_company_id', table_name='phone_numbers')
    op.drop_index('ix_phone_numbers_id', table_name='phone_numbers')
    op.drop_table('phone_numbers')

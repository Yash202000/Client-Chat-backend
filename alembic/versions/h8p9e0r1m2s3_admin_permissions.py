"""Seed the admin / compliance permissions the API checks: audit log, security events, data export,
plus settings:write and ticket:manage (used by routing rules, custom fields and ticket workflows but never seeded)

Revision ID: h8p9e0r1m2s3
Revises: g7s8i9p0r1e2
Create Date: 2026-10-14 00:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'h8p9e0r1m2s3'
down_revision: Union[str, Sequence[str], None] = 'g7s8i9p0r1e2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# same names and descriptions as role_service.PERMISSIONS
ADMIN_PERMISSIONS = {
    "audit:read": "View the audit log",
    "security_log:read": "View security events (prompt injection, rate limits)",
    "security_log:delete": "Delete security events",
    "data:export": "Export all company data (ZIP of CSVs)",
    "settings:write": "Manage routing rules and custom fields",
    "ticket:manage": "Manage ticket workflows and statuses",
}


def upgrade() -> None:
    # Startup only refreshes Super Admin, so existing company Admin roles are granted them here.
    conn = op.get_bind()
    for name, desc in ADMIN_PERMISSIONS.items():
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
    conn = op.get_bind()
    for name in ADMIN_PERMISSIONS:
        conn.execute(sa.text("DELETE FROM role_permissions WHERE permission_id IN (SELECT id FROM permissions WHERE name = :n)"), {"n": name})
        conn.execute(sa.text("DELETE FROM permissions WHERE name = :n"), {"n": name})

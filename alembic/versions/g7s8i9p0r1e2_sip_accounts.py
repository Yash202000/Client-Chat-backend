"""SIP phone accounts for system users + view read by the Kamailio registrar

Revision ID: g7s8i9p0r1e2
Revises: f6r7e8p9o0r1
Create Date: 2026-10-13 00:00:06

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'g7s8i9p0r1e2'
down_revision: Union[str, Sequence[str], None] = 'f6r7e8p9o0r1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Kamailio auth_db reads (username, ha1). Only active users with an enabled SIP account can register,
# so deactivating a user or their SIP account blocks the softphone immediately.
VIEW = """
CREATE OR REPLACE VIEW kamailio_subscriber AS
SELECT sa.username AS username, sa.ha1 AS ha1
FROM sip_accounts sa
JOIN users u ON u.id = sa.user_id
WHERE sa.enabled AND u.is_active
"""


def upgrade() -> None:
    conn = op.get_bind()
    if 'sip_accounts' not in sa.inspect(conn).get_table_names():
        op.create_table(
            'sip_accounts',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('company_id', sa.Integer(), sa.ForeignKey('companies.id'), nullable=False, index=True),
            sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, unique=True),
            # globally unique: the registrar has one realm for all companies
            sa.Column('username', sa.String(32), nullable=False, unique=True),
            sa.Column('ha1', sa.String(32), nullable=False),  # md5(username:realm:password) — SIP digest, no plain password
            sa.Column('realm', sa.String(64), nullable=False),
            sa.Column('enabled', sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
    op.execute(VIEW)


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS kamailio_subscriber")
    op.drop_table('sip_accounts')

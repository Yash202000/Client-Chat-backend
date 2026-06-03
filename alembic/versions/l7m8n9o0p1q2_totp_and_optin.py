"""add totp columns to users and opt_in_status to contacts

Revision ID: l7m8n9o0p1q2
Revises: k6l7m8n9o0p1
Create Date: 2026-05-23
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = 'l7m8n9o0p1q2'
down_revision = 'k6l7m8n9o0p1'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    user_cols = [c['name'] for c in inspect(conn).get_columns('users')]
    if 'totp_secret' not in user_cols:
        op.add_column('users', sa.Column('totp_secret', sa.String(), nullable=True))
    if 'totp_enabled' not in user_cols:
        op.add_column('users', sa.Column('totp_enabled', sa.Boolean(), nullable=False, server_default='false'))

    # Opt-in/out status on contacts
    optin_enum = sa.Enum('opted_in', 'opted_out', 'unknown', 'pending', name='optinstatus')
    optin_enum.create(op.get_bind(), checkfirst=True)
    contact_cols = [c['name'] for c in inspect(conn).get_columns('contacts')]
    if 'opt_in_status' not in contact_cols:
        op.add_column('contacts', sa.Column(
            'opt_in_status',
            sa.Enum('opted_in', 'opted_out', 'unknown', 'pending', name='optinstatus'),
            nullable=False,
            server_default='unknown',
        ))


def downgrade():
    op.drop_column('contacts', 'opt_in_status')
    op.execute("DROP TYPE IF EXISTS optinstatus")
    op.drop_column('users', 'totp_enabled')
    op.drop_column('users', 'totp_secret')

"""add_smtp_to_company_settings

Revision ID: g2b3c4d5e6f7
Revises: f1a2b3c4d5e6
Create Date: 2024-01-15 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'g2b3c4d5e6f7'
down_revision = 'f1a2b3c4d5e6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add SMTP fields to company_settings table
    op.add_column('company_settings', sa.Column('smtp_host', sa.String(), nullable=True))
    op.add_column('company_settings', sa.Column('smtp_port', sa.Integer(), nullable=True, server_default='587'))
    op.add_column('company_settings', sa.Column('smtp_user', sa.String(), nullable=True))
    op.add_column('company_settings', sa.Column('smtp_password', sa.Text(), nullable=True))
    op.add_column('company_settings', sa.Column('smtp_use_tls', sa.Boolean(), nullable=True, server_default='true'))
    op.add_column('company_settings', sa.Column('smtp_from_email', sa.String(), nullable=True))
    op.add_column('company_settings', sa.Column('smtp_from_name', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('company_settings', 'smtp_from_name')
    op.drop_column('company_settings', 'smtp_from_email')
    op.drop_column('company_settings', 'smtp_use_tls')
    op.drop_column('company_settings', 'smtp_password')
    op.drop_column('company_settings', 'smtp_user')
    op.drop_column('company_settings', 'smtp_port')
    op.drop_column('company_settings', 'smtp_host')

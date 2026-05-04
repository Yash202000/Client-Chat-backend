"""add gdpr erasure log

Revision ID: ab1c2d3e4f5a
Revises: a2b3c4d5e6f7
Create Date: 2026-05-03 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = 'ab1c2d3e4f5a'
down_revision = 'a2b3c4d5e6f7'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'gdpr_erasure_log',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('company_id', sa.Integer(), sa.ForeignKey('companies.id'), nullable=False, index=True),
        sa.Column('requested_by_email', sa.String(255), nullable=False),
        sa.Column('erasure_type', sa.String(20), nullable=False),  # 'user' or 'company'
        sa.Column('ip_address', sa.String(45), nullable=True),
        sa.Column('completed_at', sa.DateTime(), nullable=False),
    )


def downgrade():
    op.drop_table('gdpr_erasure_log')

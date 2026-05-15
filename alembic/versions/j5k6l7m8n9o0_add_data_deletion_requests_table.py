"""add data_deletion_requests table

Revision ID: j5k6l7m8n9o0
Revises: i4j5k6l7m8n9
Create Date: 2026-05-16
"""
from alembic import op
import sqlalchemy as sa

revision = 'j5k6l7m8n9o0'
down_revision = 'i4j5k6l7m8n9'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'data_deletion_requests',
        sa.Column('id', sa.Integer, primary_key=True, index=True),
        sa.Column('confirmation_code', sa.String(64), unique=True, nullable=False, index=True),
        sa.Column('request_type', sa.String(20), nullable=False, server_default='user_submitted'),
        sa.Column('email', sa.String(255), nullable=True, index=True),
        sa.Column('name', sa.String(255), nullable=True),
        sa.Column('details', sa.Text, nullable=True),
        sa.Column('facebook_user_id', sa.String(100), nullable=True, index=True),
        sa.Column('status', sa.String(20), nullable=False, server_default='pending'),
        sa.Column('created_at', sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column('processed_at', sa.DateTime, nullable=True),
    )


def downgrade():
    op.drop_table('data_deletion_requests')

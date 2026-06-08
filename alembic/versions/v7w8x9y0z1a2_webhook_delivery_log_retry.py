"""webhook_delivery_log — add retry columns (webhook_id, next_retry_at, updated_at)

Revision ID: v7w8x9y0z1a2
Revises: u6v7w8x9y0z1
Create Date: 2026-06-08
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine.reflection import Inspector

revision = 'v7w8x9y0z1a2'
down_revision = 'u6v7w8x9y0z1'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = Inspector.from_engine(bind)
    existing_cols = {c['name'] for c in inspector.get_columns('webhook_delivery_logs')}

    if 'webhook_id' not in existing_cols:
        op.add_column(
            'webhook_delivery_logs',
            sa.Column('webhook_id', sa.Integer(), nullable=True),
        )

    if 'next_retry_at' not in existing_cols:
        op.add_column(
            'webhook_delivery_logs',
            sa.Column('next_retry_at', sa.DateTime(), nullable=True),
        )

    if 'updated_at' not in existing_cols:
        op.add_column(
            'webhook_delivery_logs',
            sa.Column('updated_at', sa.DateTime(), nullable=True),
        )


def downgrade():
    bind = op.get_bind()
    inspector = Inspector.from_engine(bind)
    existing_cols = {c['name'] for c in inspector.get_columns('webhook_delivery_logs')}

    if 'updated_at' in existing_cols:
        op.drop_column('webhook_delivery_logs', 'updated_at')
    if 'next_retry_at' in existing_cols:
        op.drop_column('webhook_delivery_logs', 'next_retry_at')
    if 'webhook_id' in existing_cols:
        op.drop_column('webhook_delivery_logs', 'webhook_id')

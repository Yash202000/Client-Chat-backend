"""email_storage_limits — monthly email cap, storage quota

Revision ID: t5u6v7w8x9y0
Revises: s4t5u6v7w8x9
Create Date: 2026-06-08
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine.reflection import Inspector

revision = 't5u6v7w8x9y0'
down_revision = 's4t5u6v7w8x9'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = Inspector.from_engine(bind)

    # subscription_plans — new limit columns
    plan_cols = {c['name'] for c in inspector.get_columns('subscription_plans')}
    if 'max_monthly_emails' not in plan_cols:
        op.add_column('subscription_plans', sa.Column('max_monthly_emails', sa.Integer(), nullable=True))
    if 'max_storage_bytes' not in plan_cols:
        op.add_column('subscription_plans', sa.Column('max_storage_bytes', sa.BigInteger(), nullable=True))

    # company_subscriptions — usage tracking
    sub_cols = {c['name'] for c in inspector.get_columns('company_subscriptions')}
    if 'monthly_email_count' not in sub_cols:
        op.add_column('company_subscriptions', sa.Column(
            'monthly_email_count', sa.Integer(), nullable=False, server_default='0'))
    if 'email_count_reset_at' not in sub_cols:
        op.add_column('company_subscriptions', sa.Column(
            'email_count_reset_at', sa.DateTime(), nullable=True))
    if 'total_storage_bytes' not in sub_cols:
        op.add_column('company_subscriptions', sa.Column(
            'total_storage_bytes', sa.BigInteger(), nullable=False, server_default='0'))


def downgrade():
    op.drop_column('company_subscriptions', 'total_storage_bytes')
    op.drop_column('company_subscriptions', 'email_count_reset_at')
    op.drop_column('company_subscriptions', 'monthly_email_count')
    op.drop_column('subscription_plans', 'max_storage_bytes')
    op.drop_column('subscription_plans', 'max_monthly_emails')

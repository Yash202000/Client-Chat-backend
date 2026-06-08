"""agent_limits_and_email_verify — agent quotas, conversation counter, email/phone verification

Revision ID: p1q2r3s4t5u6
Revises: o0p1q2r3s4t5
Create Date: 2026-06-08
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine.reflection import Inspector

revision = 'p1q2r3s4t5u6'
down_revision = 'o0p1q2r3s4t5'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = Inspector.from_engine(bind)

    # ── subscription_plans — agent limit columns ───────────────────────────────
    plan_cols = {c['name'] for c in inspector.get_columns('subscription_plans')}
    if 'max_agents' not in plan_cols:
        op.add_column('subscription_plans', sa.Column('max_agents', sa.Integer(), nullable=True))
    if 'max_active_agents' not in plan_cols:
        op.add_column('subscription_plans', sa.Column('max_active_agents', sa.Integer(), nullable=True))
    if 'max_monthly_conversations' not in plan_cols:
        op.add_column('subscription_plans', sa.Column('max_monthly_conversations', sa.Integer(), nullable=True))
    if 'max_kb_upload_bytes' not in plan_cols:
        op.add_column('subscription_plans', sa.Column('max_kb_upload_bytes', sa.Integer(), nullable=True))

    # ── company_subscriptions — conversation counter ───────────────────────────
    sub_cols = {c['name'] for c in inspector.get_columns('company_subscriptions')}
    if 'monthly_conversation_count' not in sub_cols:
        op.add_column('company_subscriptions', sa.Column(
            'monthly_conversation_count', sa.Integer(), nullable=False, server_default='0'))
    if 'conversation_count_reset_at' not in sub_cols:
        op.add_column('company_subscriptions', sa.Column(
            'conversation_count_reset_at', sa.DateTime(), nullable=True))

    # ── users — email and phone verification ──────────────────────────────────
    user_cols = {c['name'] for c in inspector.get_columns('users')}
    if 'email_verified' not in user_cols:
        op.add_column('users', sa.Column(
            'email_verified', sa.Boolean(), nullable=False, server_default='false'))
    if 'phone_verified' not in user_cols:
        op.add_column('users', sa.Column(
            'phone_verified', sa.Boolean(), nullable=False, server_default='false'))


def downgrade():
    op.drop_column('users', 'phone_verified')
    op.drop_column('users', 'email_verified')
    op.drop_column('company_subscriptions', 'conversation_count_reset_at')
    op.drop_column('company_subscriptions', 'monthly_conversation_count')
    op.drop_column('subscription_plans', 'max_kb_upload_bytes')
    op.drop_column('subscription_plans', 'max_monthly_conversations')
    op.drop_column('subscription_plans', 'max_active_agents')
    op.drop_column('subscription_plans', 'max_agents')

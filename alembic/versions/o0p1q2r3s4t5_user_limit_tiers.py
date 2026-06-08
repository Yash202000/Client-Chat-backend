"""user_limit_tiers — warn thresholds, addon seats, grace periods per plan

Revision ID: o0p1q2r3s4t5
Revises: n9o0p1q2r3s4
Create Date: 2026-06-08
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine.reflection import Inspector

revision = 'o0p1q2r3s4t5'
down_revision = 'n9o0p1q2r3s4'
branch_labels = None
depends_on = None


def _col_exists(inspector, table, column):
    return any(c['name'] == column for c in inspector.get_columns(table))


def upgrade():
    bind = op.get_bind()
    inspector = Inspector.from_engine(bind)

    # ── subscription_plans ────────────────────────────────────────────────────
    plan_cols = {c['name'] for c in inspector.get_columns('subscription_plans')}

    if 'warn_threshold' not in plan_cols:
        op.add_column('subscription_plans', sa.Column('warn_threshold', sa.Integer(), nullable=True))
    if 'addon_seat_cap' not in plan_cols:
        op.add_column('subscription_plans', sa.Column('addon_seat_cap', sa.Integer(), nullable=False, server_default='0'))
    if 'addon_seat_price_usd' not in plan_cols:
        op.add_column('subscription_plans', sa.Column('addon_seat_price_usd', sa.Float(), nullable=True))
    if 'addon_seat_price_inr' not in plan_cols:
        op.add_column('subscription_plans', sa.Column('addon_seat_price_inr', sa.Float(), nullable=True))
    if 'grace_period_days' not in plan_cols:
        op.add_column('subscription_plans', sa.Column('grace_period_days', sa.Integer(), nullable=False, server_default='0'))

    # ── company_subscriptions ─────────────────────────────────────────────────
    sub_cols = {c['name'] for c in inspector.get_columns('company_subscriptions')}

    if 'addon_seats' not in sub_cols:
        op.add_column('company_subscriptions', sa.Column('addon_seats', sa.Integer(), nullable=False, server_default='0'))
    if 'grace_period_end' not in sub_cols:
        op.add_column('company_subscriptions', sa.Column('grace_period_end', sa.DateTime(), nullable=True))


def downgrade():
    op.drop_column('company_subscriptions', 'grace_period_end')
    op.drop_column('company_subscriptions', 'addon_seats')
    op.drop_column('subscription_plans', 'grace_period_days')
    op.drop_column('subscription_plans', 'addon_seat_price_inr')
    op.drop_column('subscription_plans', 'addon_seat_price_usd')
    op.drop_column('subscription_plans', 'addon_seat_cap')
    op.drop_column('subscription_plans', 'warn_threshold')

"""Add company subscription table and update subscription plans

Revision ID: h7i8j9k0l1m2
Revises: g6h7i8j9k0l1
Create Date: 2026-01-25

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'h7i8j9k0l1m2'
down_revision: Union[str, None] = 'g6h7i8j9k0l1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add company subscription table and update subscription plans with Stripe fields."""

    # 1. Add new columns to subscription_plans table
    op.add_column('subscription_plans', sa.Column('stripe_price_id', sa.String(), nullable=True))
    op.add_column('subscription_plans', sa.Column('stripe_product_id', sa.String(), nullable=True))
    op.add_column('subscription_plans', sa.Column('default_user_limit', sa.Integer(), server_default='5', nullable=False))
    op.add_column('subscription_plans', sa.Column('trial_days', sa.Integer(), server_default='14', nullable=False))
    op.add_column('subscription_plans', sa.Column('description', sa.Text(), nullable=True))
    op.add_column('subscription_plans', sa.Column('billing_interval', sa.String(), server_default='month', nullable=True))

    # Create indexes for Stripe IDs
    op.create_index(op.f('ix_subscription_plans_stripe_price_id'), 'subscription_plans', ['stripe_price_id'], unique=False)
    op.create_index(op.f('ix_subscription_plans_stripe_product_id'), 'subscription_plans', ['stripe_product_id'], unique=False)

    # 2. Create company_subscriptions table
    op.create_table(
        'company_subscriptions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('company_id', sa.Integer(), nullable=False),
        sa.Column('subscription_plan_id', sa.Integer(), nullable=True),
        sa.Column('stripe_customer_id', sa.String(), nullable=True),
        sa.Column('stripe_subscription_id', sa.String(), nullable=True),
        sa.Column('status', sa.String(), server_default='trial', nullable=False),
        sa.Column('trial_start_date', sa.DateTime(), nullable=True),
        sa.Column('trial_end_date', sa.DateTime(), nullable=True),
        sa.Column('current_period_start', sa.DateTime(), nullable=True),
        sa.Column('current_period_end', sa.DateTime(), nullable=True),
        sa.Column('user_limit', sa.Integer(), server_default='5', nullable=False),
        sa.Column('cancel_at_period_end', sa.Boolean(), server_default='false', nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['subscription_plan_id'], ['subscription_plans.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )

    # Create indexes
    op.create_index(op.f('ix_company_subscriptions_id'), 'company_subscriptions', ['id'], unique=False)
    op.create_index(op.f('ix_company_subscriptions_company_id'), 'company_subscriptions', ['company_id'], unique=True)
    op.create_index(op.f('ix_company_subscriptions_stripe_customer_id'), 'company_subscriptions', ['stripe_customer_id'], unique=False)
    op.create_index(op.f('ix_company_subscriptions_stripe_subscription_id'), 'company_subscriptions', ['stripe_subscription_id'], unique=False)


def downgrade() -> None:
    """Remove company subscription table and revert subscription plans changes."""

    # 1. Drop company_subscriptions table
    op.drop_index(op.f('ix_company_subscriptions_stripe_subscription_id'), table_name='company_subscriptions')
    op.drop_index(op.f('ix_company_subscriptions_stripe_customer_id'), table_name='company_subscriptions')
    op.drop_index(op.f('ix_company_subscriptions_company_id'), table_name='company_subscriptions')
    op.drop_index(op.f('ix_company_subscriptions_id'), table_name='company_subscriptions')
    op.drop_table('company_subscriptions')

    # 2. Remove columns from subscription_plans table
    op.drop_index(op.f('ix_subscription_plans_stripe_product_id'), table_name='subscription_plans')
    op.drop_index(op.f('ix_subscription_plans_stripe_price_id'), table_name='subscription_plans')
    op.drop_column('subscription_plans', 'billing_interval')
    op.drop_column('subscription_plans', 'description')
    op.drop_column('subscription_plans', 'trial_days')
    op.drop_column('subscription_plans', 'default_user_limit')
    op.drop_column('subscription_plans', 'stripe_product_id')
    op.drop_column('subscription_plans', 'stripe_price_id')

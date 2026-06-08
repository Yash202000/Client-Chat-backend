"""trial_dunning_tracking — trial email flags and dunning tracking columns

Revision ID: u6v7w8x9y0z1
Revises: t5u6v7w8x9y0
Create Date: 2026-06-08
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine.reflection import Inspector

revision = 'u6v7w8x9y0z1'
down_revision = 't5u6v7w8x9y0'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = Inspector.from_engine(bind)
    sub_cols = {c['name'] for c in inspector.get_columns('company_subscriptions')}

    if 'trial_welcome_sent' not in sub_cols:
        op.add_column('company_subscriptions', sa.Column(
            'trial_welcome_sent', sa.Boolean(), nullable=False, server_default='false'))
    if 'trial_day7_sent' not in sub_cols:
        op.add_column('company_subscriptions', sa.Column(
            'trial_day7_sent', sa.Boolean(), nullable=False, server_default='false'))
    if 'trial_day12_sent' not in sub_cols:
        op.add_column('company_subscriptions', sa.Column(
            'trial_day12_sent', sa.Boolean(), nullable=False, server_default='false'))
    if 'trial_expiry_sent' not in sub_cols:
        op.add_column('company_subscriptions', sa.Column(
            'trial_expiry_sent', sa.Boolean(), nullable=False, server_default='false'))
    if 'dunning_attempt_1_sent' not in sub_cols:
        op.add_column('company_subscriptions', sa.Column(
            'dunning_attempt_1_sent', sa.Boolean(), nullable=False, server_default='false'))
    if 'dunning_attempt_2_sent' not in sub_cols:
        op.add_column('company_subscriptions', sa.Column(
            'dunning_attempt_2_sent', sa.Boolean(), nullable=False, server_default='false'))
    if 'dunning_attempt_3_sent' not in sub_cols:
        op.add_column('company_subscriptions', sa.Column(
            'dunning_attempt_3_sent', sa.Boolean(), nullable=False, server_default='false'))
    if 'last_dunning_sent_at' not in sub_cols:
        op.add_column('company_subscriptions', sa.Column(
            'last_dunning_sent_at', sa.DateTime(), nullable=True))


def downgrade():
    op.drop_column('company_subscriptions', 'last_dunning_sent_at')
    op.drop_column('company_subscriptions', 'dunning_attempt_3_sent')
    op.drop_column('company_subscriptions', 'dunning_attempt_2_sent')
    op.drop_column('company_subscriptions', 'dunning_attempt_1_sent')
    op.drop_column('company_subscriptions', 'trial_expiry_sent')
    op.drop_column('company_subscriptions', 'trial_day12_sent')
    op.drop_column('company_subscriptions', 'trial_day7_sent')
    op.drop_column('company_subscriptions', 'trial_welcome_sent')

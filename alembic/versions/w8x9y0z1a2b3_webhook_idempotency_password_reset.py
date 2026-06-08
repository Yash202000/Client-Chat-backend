"""webhook idempotency and password reset tokens

Revision ID: w8x9y0z1a2b3
Revises: v7w8x9y0z1a2
Create Date: 2026-06-08 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = 'w8x9y0z1a2b3'
down_revision = 'v7w8x9y0z1a2'
branch_labels = None
depends_on = None


def upgrade():
    # Razorpay processed event IDs — prevents double-processing of retried webhooks
    op.create_table(
        'razorpay_processed_events',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('event_id', sa.String(), nullable=False),
        sa.Column('event_type', sa.String(), nullable=True),
        sa.Column('processed_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('event_id'),
    )
    op.create_index('ix_razorpay_processed_events_event_id', 'razorpay_processed_events', ['event_id'], unique=True)

    # Password reset tokens
    op.create_table(
        'password_reset_tokens',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('token', sa.String(), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.Column('used', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('token'),
    )
    op.create_index('ix_password_reset_tokens_token', 'password_reset_tokens', ['token'], unique=True)
    op.create_index('ix_password_reset_tokens_user_id', 'password_reset_tokens', ['user_id'])


def downgrade():
    op.drop_table('password_reset_tokens')
    op.drop_table('razorpay_processed_events')

"""add token tracking tables

Revision ID: b1c2d3e4f5g6
Revises: a07c135714c8
Create Date: 2026-01-08 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b1c2d3e4f5g6'
down_revision: Union[str, Sequence[str], None] = 'a07c135714c8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add token tracking columns to company_settings table
    op.add_column('company_settings', sa.Column('token_tracking_mode', sa.String(length=20), nullable=True, server_default='detailed'))
    op.add_column('company_settings', sa.Column('monthly_budget_cents', sa.Integer(), nullable=True))
    op.add_column('company_settings', sa.Column('alert_threshold_percent', sa.Integer(), nullable=True, server_default='80'))
    op.add_column('company_settings', sa.Column('alert_email', sa.String(length=255), nullable=True))
    op.add_column('company_settings', sa.Column('alerts_enabled', sa.Boolean(), nullable=True, server_default='true'))
    op.add_column('company_settings', sa.Column('per_agent_daily_limit_cents', sa.Integer(), nullable=True))

    # Create token_usage table
    op.create_table(
        'token_usage',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('company_id', sa.Integer(), nullable=False),
        sa.Column('agent_id', sa.Integer(), nullable=True),
        sa.Column('session_id', sa.String(length=255), nullable=True),
        sa.Column('provider', sa.String(length=50), nullable=False),
        sa.Column('model_name', sa.String(length=100), nullable=False),
        sa.Column('prompt_tokens', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('completion_tokens', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('total_tokens', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('estimated_cost_cents', sa.Integer(), nullable=True),
        sa.Column('request_type', sa.String(length=50), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ),
        sa.ForeignKeyConstraint(['agent_id'], ['agents.id'], ),
        sa.PrimaryKeyConstraint('id')
    )

    # Create indexes for token_usage
    op.create_index(op.f('ix_token_usage_id'), 'token_usage', ['id'], unique=False)
    op.create_index(op.f('ix_token_usage_company_id'), 'token_usage', ['company_id'], unique=False)
    op.create_index(op.f('ix_token_usage_agent_id'), 'token_usage', ['agent_id'], unique=False)
    op.create_index(op.f('ix_token_usage_session_id'), 'token_usage', ['session_id'], unique=False)
    op.create_index(op.f('ix_token_usage_created_at'), 'token_usage', ['created_at'], unique=False)
    op.create_index('ix_token_usage_company_created', 'token_usage', ['company_id', 'created_at'], unique=False)
    op.create_index('ix_token_usage_agent_created', 'token_usage', ['agent_id', 'created_at'], unique=False)
    op.create_index('ix_token_usage_provider_model', 'token_usage', ['provider', 'model_name'], unique=False)

    # Create usage_alerts table
    op.create_table(
        'usage_alerts',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('company_id', sa.Integer(), nullable=False),
        sa.Column('agent_id', sa.Integer(), nullable=True),
        sa.Column('alert_type', sa.String(length=50), nullable=False),
        sa.Column('threshold_value', sa.Integer(), nullable=False),
        sa.Column('current_value', sa.Integer(), nullable=False),
        sa.Column('message', sa.Text(), nullable=True),
        sa.Column('acknowledged', sa.Boolean(), nullable=True, server_default='false'),
        sa.Column('acknowledged_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('acknowledged_by', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ),
        sa.ForeignKeyConstraint(['agent_id'], ['agents.id'], ),
        sa.ForeignKeyConstraint(['acknowledged_by'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id')
    )

    # Create indexes for usage_alerts
    op.create_index(op.f('ix_usage_alerts_id'), 'usage_alerts', ['id'], unique=False)
    op.create_index(op.f('ix_usage_alerts_company_id'), 'usage_alerts', ['company_id'], unique=False)
    op.create_index(op.f('ix_usage_alerts_alert_type'), 'usage_alerts', ['alert_type'], unique=False)
    op.create_index(op.f('ix_usage_alerts_created_at'), 'usage_alerts', ['created_at'], unique=False)
    op.create_index('ix_usage_alerts_company_created', 'usage_alerts', ['company_id', 'created_at'], unique=False)
    op.create_index('ix_usage_alerts_company_unack', 'usage_alerts', ['company_id', 'acknowledged'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    # Drop usage_alerts table and indexes
    op.drop_index('ix_usage_alerts_company_unack', table_name='usage_alerts')
    op.drop_index('ix_usage_alerts_company_created', table_name='usage_alerts')
    op.drop_index(op.f('ix_usage_alerts_created_at'), table_name='usage_alerts')
    op.drop_index(op.f('ix_usage_alerts_alert_type'), table_name='usage_alerts')
    op.drop_index(op.f('ix_usage_alerts_company_id'), table_name='usage_alerts')
    op.drop_index(op.f('ix_usage_alerts_id'), table_name='usage_alerts')
    op.drop_table('usage_alerts')

    # Drop token_usage table and indexes
    op.drop_index('ix_token_usage_provider_model', table_name='token_usage')
    op.drop_index('ix_token_usage_agent_created', table_name='token_usage')
    op.drop_index('ix_token_usage_company_created', table_name='token_usage')
    op.drop_index(op.f('ix_token_usage_created_at'), table_name='token_usage')
    op.drop_index(op.f('ix_token_usage_session_id'), table_name='token_usage')
    op.drop_index(op.f('ix_token_usage_agent_id'), table_name='token_usage')
    op.drop_index(op.f('ix_token_usage_company_id'), table_name='token_usage')
    op.drop_index(op.f('ix_token_usage_id'), table_name='token_usage')
    op.drop_table('token_usage')

    # Remove token tracking columns from company_settings
    op.drop_column('company_settings', 'per_agent_daily_limit_cents')
    op.drop_column('company_settings', 'alerts_enabled')
    op.drop_column('company_settings', 'alert_email')
    op.drop_column('company_settings', 'alert_threshold_percent')
    op.drop_column('company_settings', 'monthly_budget_cents')
    op.drop_column('company_settings', 'token_tracking_mode')

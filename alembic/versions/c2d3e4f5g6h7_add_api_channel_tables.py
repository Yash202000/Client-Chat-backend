"""add api channel tables

Revision ID: c2d3e4f5g6h7
Revises: b1c2d3e4f5g6
Create Date: 2026-01-10 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c2d3e4f5g6h7'
down_revision: Union[str, Sequence[str], None] = 'b1c2d3e4f5g6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add new columns to api_keys table
    op.add_column('api_keys', sa.Column('expires_at', sa.DateTime(), nullable=True))
    op.add_column('api_keys', sa.Column('scopes', sa.JSON(), nullable=True))
    op.add_column('api_keys', sa.Column('last_used_at', sa.DateTime(), nullable=True))
    op.add_column('api_keys', sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'))

    # Create api_integrations table
    op.create_table(
        'api_integrations',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('description', sa.String(), nullable=True),
        sa.Column('api_key_id', sa.Integer(), nullable=False),
        sa.Column('company_id', sa.Integer(), nullable=False),
        sa.Column('webhook_url', sa.String(), nullable=True),
        sa.Column('webhook_secret', sa.String(), nullable=True),
        sa.Column('webhook_enabled', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('sync_response', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('default_agent_id', sa.Integer(), nullable=True),
        sa.Column('default_workflow_id', sa.Integer(), nullable=True),
        sa.Column('rate_limit_requests', sa.Integer(), nullable=True),
        sa.Column('rate_limit_window', sa.Integer(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('extra_config', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['api_key_id'], ['api_keys.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['default_agent_id'], ['agents.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['default_workflow_id'], ['workflows.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('api_key_id')
    )

    # Create indexes for api_integrations
    op.create_index(op.f('ix_api_integrations_id'), 'api_integrations', ['id'], unique=False)
    op.create_index(op.f('ix_api_integrations_company_id'), 'api_integrations', ['company_id'], unique=False)
    op.create_index(op.f('ix_api_integrations_api_key_id'), 'api_integrations', ['api_key_id'], unique=True)


def downgrade() -> None:
    """Downgrade schema."""
    # Drop api_integrations table and indexes
    op.drop_index(op.f('ix_api_integrations_api_key_id'), table_name='api_integrations')
    op.drop_index(op.f('ix_api_integrations_company_id'), table_name='api_integrations')
    op.drop_index(op.f('ix_api_integrations_id'), table_name='api_integrations')
    op.drop_table('api_integrations')

    # Remove new columns from api_keys
    op.drop_column('api_keys', 'is_active')
    op.drop_column('api_keys', 'last_used_at')
    op.drop_column('api_keys', 'scopes')
    op.drop_column('api_keys', 'expires_at')

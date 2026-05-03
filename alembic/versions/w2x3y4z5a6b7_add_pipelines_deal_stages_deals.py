"""add pipelines, deal_stages, deals tables

Revision ID: w2x3y4z5a6b7
Revises: v1w2x3y4z5a6
Create Date: 2026-05-01

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'w2x3y4z5a6b7'
down_revision = 'v1w2x3y4z5a6'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'pipelines',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('company_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('is_default', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_pipelines_id', 'pipelines', ['id'])
    op.create_index('ix_pipelines_company_id', 'pipelines', ['company_id'])

    op.create_table(
        'deal_stages',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('pipeline_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('position', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('probability', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('color', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['pipeline_id'], ['pipelines.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_deal_stages_id', 'deal_stages', ['id'])
    op.create_index('ix_deal_stages_pipeline_id', 'deal_stages', ['pipeline_id'])

    op.create_table(
        'deals',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('company_id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(), nullable=False),
        sa.Column('amount', sa.DECIMAL(precision=15, scale=2), nullable=True),
        sa.Column('currency', sa.String(3), nullable=False, server_default='USD'),
        sa.Column('status', sa.Enum('open', 'won', 'lost', name='dealstatus'), nullable=False, server_default='open'),
        sa.Column('pipeline_id', sa.Integer(), nullable=False),
        sa.Column('stage_id', sa.Integer(), nullable=False),
        sa.Column('contact_id', sa.Integer(), nullable=True),
        sa.Column('account_id', sa.Integer(), nullable=True),
        sa.Column('owner_id', sa.Integer(), nullable=True),
        sa.Column('expected_close_date', sa.DateTime(), nullable=True),
        sa.Column('actual_close_date', sa.DateTime(), nullable=True),
        sa.Column('won_reason', sa.String(), nullable=True),
        sa.Column('lost_reason', sa.String(), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('custom_fields', postgresql.JSONB(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['pipeline_id'], ['pipelines.id']),
        sa.ForeignKeyConstraint(['stage_id'], ['deal_stages.id']),
        sa.ForeignKeyConstraint(['contact_id'], ['contacts.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['account_id'], ['accounts.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_deals_id', 'deals', ['id'])
    op.create_index('ix_deals_title', 'deals', ['title'])
    op.create_index('ix_deals_company_id', 'deals', ['company_id'])
    op.create_index('ix_deals_pipeline_id', 'deals', ['pipeline_id'])
    op.create_index('ix_deals_stage_id', 'deals', ['stage_id'])
    op.create_index('ix_deals_contact_id', 'deals', ['contact_id'])
    op.create_index('ix_deals_account_id', 'deals', ['account_id'])
    op.create_index('ix_deals_owner_id', 'deals', ['owner_id'])
    op.create_index('ix_deals_status', 'deals', ['status'])


def downgrade():
    op.drop_table('deals')
    op.execute("DROP TYPE IF EXISTS dealstatus")
    op.drop_table('deal_stages')
    op.drop_table('pipelines')

"""add accounts table and contact account_id fk

Revision ID: v1w2x3y4z5a6
Revises: u0v1w2x3y4z5
Create Date: 2026-05-01

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'v1w2x3y4z5a6'
down_revision = 'u0v1w2x3y4z5'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'accounts',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('company_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('domain', sa.String(), nullable=True),
        sa.Column('industry', sa.String(), nullable=True),
        sa.Column('employee_count', sa.Integer(), nullable=True),
        sa.Column('annual_revenue', sa.DECIMAL(precision=15, scale=2), nullable=True),
        sa.Column('phone', sa.String(), nullable=True),
        sa.Column('website', sa.String(), nullable=True),
        sa.Column('address_street', sa.String(), nullable=True),
        sa.Column('address_city', sa.String(), nullable=True),
        sa.Column('address_state', sa.String(), nullable=True),
        sa.Column('address_country', sa.String(), nullable=True),
        sa.Column('address_zip', sa.String(), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('owner_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_accounts_id', 'accounts', ['id'])
    op.create_index('ix_accounts_name', 'accounts', ['name'])
    op.create_index('ix_accounts_domain', 'accounts', ['domain'])
    op.create_index('ix_accounts_industry', 'accounts', ['industry'])
    op.create_index('ix_accounts_company_id', 'accounts', ['company_id'])
    op.create_index('ix_accounts_owner_id', 'accounts', ['owner_id'])

    # Link contacts to accounts (CRM B2B relation)
    op.add_column('contacts', sa.Column('account_id', sa.Integer(), nullable=True))
    op.create_foreign_key(
        'fk_contacts_account_id', 'contacts', 'accounts',
        ['account_id'], ['id'], ondelete='SET NULL'
    )
    op.create_index('ix_contacts_account_id', 'contacts', ['account_id'])


def downgrade():
    op.drop_index('ix_contacts_account_id', table_name='contacts')
    op.drop_constraint('fk_contacts_account_id', 'contacts', type_='foreignkey')
    op.drop_column('contacts', 'account_id')

    op.drop_index('ix_accounts_owner_id', table_name='accounts')
    op.drop_index('ix_accounts_company_id', table_name='accounts')
    op.drop_index('ix_accounts_industry', table_name='accounts')
    op.drop_index('ix_accounts_domain', table_name='accounts')
    op.drop_index('ix_accounts_name', table_name='accounts')
    op.drop_index('ix_accounts_id', table_name='accounts')
    op.drop_table('accounts')

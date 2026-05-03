"""add contact_activities table

Revision ID: a2b3c4d5e6f7
Revises: e1f2a3b4c5d6
Create Date: 2026-05-02

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'a2b3c4d5e6f7'
down_revision = 'e1f2a3b4c5d6'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'contact_activities',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('contact_id', sa.Integer(), nullable=False),
        sa.Column('company_id', sa.Integer(), nullable=False),
        sa.Column('activity_type', sa.String(length=50), nullable=False),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('entity_type', sa.String(length=50), nullable=True),
        sa.Column('entity_id', sa.Integer(), nullable=True),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('extra_data', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('occurred_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ),
        sa.ForeignKeyConstraint(['contact_id'], ['contacts.id'], ),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_contact_activities_id', 'contact_activities', ['id'], unique=False)
    op.create_index('ix_contact_activities_contact_id', 'contact_activities', ['contact_id'], unique=False)
    op.create_index('ix_contact_activities_company_id', 'contact_activities', ['company_id'], unique=False)
    op.create_index('ix_contact_activities_occurred_at', 'contact_activities', ['occurred_at'], unique=False)
    op.create_index('ix_contact_activities_activity_type', 'contact_activities', ['activity_type'], unique=False)
    op.create_index('ix_contact_activities_user_id', 'contact_activities', ['user_id'], unique=False)


def downgrade():
    op.drop_index('ix_contact_activities_user_id', table_name='contact_activities')
    op.drop_index('ix_contact_activities_activity_type', table_name='contact_activities')
    op.drop_index('ix_contact_activities_occurred_at', table_name='contact_activities')
    op.drop_index('ix_contact_activities_company_id', table_name='contact_activities')
    op.drop_index('ix_contact_activities_contact_id', table_name='contact_activities')
    op.drop_index('ix_contact_activities_id', table_name='contact_activities')
    op.drop_table('contact_activities')

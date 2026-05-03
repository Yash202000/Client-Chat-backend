"""add capture_forms and form_submissions tables

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
Create Date: 2026-05-02

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'c9d0e1f2a3b4'
down_revision = 'b8c9d0e1f2a3'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'capture_forms',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('company_id', sa.Integer(), sa.ForeignKey('companies.id'), nullable=False),
        sa.Column('slug', sa.String(), nullable=False),
        sa.Column('status', sa.String(), nullable=False, server_default='active'),
        sa.Column('fields', postgresql.JSONB(), nullable=False, server_default='[]'),
        sa.Column('settings', postgresql.JSONB(), nullable=False, server_default='{}'),
        sa.Column('created_by_user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('slug'),
    )
    op.create_index('ix_capture_forms_id', 'capture_forms', ['id'])
    op.create_index('ix_capture_forms_name', 'capture_forms', ['name'])
    op.create_index('ix_capture_forms_company_id', 'capture_forms', ['company_id'])
    op.create_index('ix_capture_forms_slug', 'capture_forms', ['slug'])

    op.create_table(
        'form_submissions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('form_id', sa.Integer(), sa.ForeignKey('capture_forms.id'), nullable=False),
        sa.Column('data', postgresql.JSONB(), nullable=False),
        sa.Column('contact_id', sa.Integer(), sa.ForeignKey('contacts.id'), nullable=True),
        sa.Column('ip_address', sa.String(), nullable=True),
        sa.Column('submitted_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_form_submissions_id', 'form_submissions', ['id'])
    op.create_index('ix_form_submissions_form_id', 'form_submissions', ['form_id'])
    op.create_index('ix_form_submissions_contact_id', 'form_submissions', ['contact_id'])


def downgrade():
    op.drop_table('form_submissions')
    op.drop_table('capture_forms')

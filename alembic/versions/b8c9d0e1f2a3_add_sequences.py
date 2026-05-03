"""add sequences tables

Revision ID: b8c9d0e1f2a3
Revises: a6b7c8d9e0f1
Create Date: 2026-05-02

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'b8c9d0e1f2a3'
down_revision = 'a6b7c8d9e0f1'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'sequences',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('company_id', sa.Integer(), sa.ForeignKey('companies.id'), nullable=False),
        sa.Column('status', sa.String(), nullable=False, server_default='draft'),
        sa.Column('goal', sa.String(), nullable=True),
        sa.Column('tags', postgresql.JSONB(), nullable=True),
        sa.Column('created_by_user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_sequences_id', 'sequences', ['id'])
    op.create_index('ix_sequences_name', 'sequences', ['name'])
    op.create_index('ix_sequences_company_id', 'sequences', ['company_id'])
    op.create_index('ix_sequences_status', 'sequences', ['status'])

    op.create_table(
        'sequence_steps',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('sequence_id', sa.Integer(), sa.ForeignKey('sequences.id'), nullable=False),
        sa.Column('step_order', sa.Integer(), nullable=False),
        sa.Column('step_type', sa.String(), nullable=False, server_default='email'),
        sa.Column('template_id', sa.Integer(), sa.ForeignKey('templates.id'), nullable=True),
        sa.Column('delay_days', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('delay_hours', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('subject', sa.String(), nullable=True),
        sa.Column('body', sa.Text(), nullable=True),
        sa.Column('condition', sa.String(), nullable=False, server_default='always'),
        sa.Column('task_note', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_sequence_steps_id', 'sequence_steps', ['id'])
    op.create_index('ix_sequence_steps_sequence_id', 'sequence_steps', ['sequence_id'])

    op.create_table(
        'sequence_enrollments',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('sequence_id', sa.Integer(), sa.ForeignKey('sequences.id'), nullable=False),
        sa.Column('contact_id', sa.Integer(), sa.ForeignKey('contacts.id'), nullable=False),
        sa.Column('status', sa.String(), nullable=False, server_default='active'),
        sa.Column('current_step', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('enrolled_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('next_send_at', sa.DateTime(), nullable=True),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.Column('enrolled_by_user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_sequence_enrollments_id', 'sequence_enrollments', ['id'])
    op.create_index('ix_sequence_enrollments_sequence_id', 'sequence_enrollments', ['sequence_id'])
    op.create_index('ix_sequence_enrollments_contact_id', 'sequence_enrollments', ['contact_id'])
    op.create_index('ix_sequence_enrollments_status', 'sequence_enrollments', ['status'])

    op.create_table(
        'sequence_step_logs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('enrollment_id', sa.Integer(), sa.ForeignKey('sequence_enrollments.id'), nullable=False),
        sa.Column('step_id', sa.Integer(), sa.ForeignKey('sequence_steps.id'), nullable=False),
        sa.Column('status', sa.String(), nullable=False, server_default='pending'),
        sa.Column('sent_at', sa.DateTime(), nullable=True),
        sa.Column('error', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_sequence_step_logs_id', 'sequence_step_logs', ['id'])
    op.create_index('ix_sequence_step_logs_enrollment_id', 'sequence_step_logs', ['enrollment_id'])


def downgrade():
    op.drop_table('sequence_step_logs')
    op.drop_table('sequence_enrollments')
    op.drop_table('sequence_steps')
    op.drop_table('sequences')

"""create_ticket_core_tables

Revision ID: e1f2a3b4c5d6
Revises: eeab9d60d728
Create Date: 2026-05-11 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'e1f2a3b4c5d6'
down_revision: Union[str, Sequence[str], None] = 'eeab9d60d728'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- ticket_workflows ---
    op.create_table(
        'ticket_workflows',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('company_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('is_default', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_ticket_workflows_id'), 'ticket_workflows', ['id'], unique=False)
    op.create_index(op.f('ix_ticket_workflows_company_id'), 'ticket_workflows', ['company_id'], unique=False)

    # --- ticket_statuses ---
    op.create_table(
        'ticket_statuses',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('workflow_id', sa.Integer(), nullable=False),
        sa.Column('company_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('color', sa.String(7), nullable=False, server_default='#6366f1'),
        sa.Column('category', sa.Enum('todo', 'in_progress', 'done', name='statuscategory'), nullable=False, server_default='todo'),
        sa.Column('position', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('is_default', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['workflow_id'], ['ticket_workflows.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_ticket_statuses_id'), 'ticket_statuses', ['id'], unique=False)
    op.create_index(op.f('ix_ticket_statuses_workflow_id'), 'ticket_statuses', ['workflow_id'], unique=False)
    op.create_index(op.f('ix_ticket_statuses_company_id'), 'ticket_statuses', ['company_id'], unique=False)

    # --- ticket_transitions ---
    op.create_table(
        'ticket_transitions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('workflow_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('from_status_id', sa.Integer(), nullable=True),
        sa.Column('to_status_id', sa.Integer(), nullable=False),
        sa.Column('conditions', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('screen_fields', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['workflow_id'], ['ticket_workflows.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['from_status_id'], ['ticket_statuses.id']),
        sa.ForeignKeyConstraint(['to_status_id'], ['ticket_statuses.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_ticket_transitions_id'), 'ticket_transitions', ['id'], unique=False)
    op.create_index(op.f('ix_ticket_transitions_workflow_id'), 'ticket_transitions', ['workflow_id'], unique=False)

    # --- ticket_issue_types ---
    op.create_table(
        'ticket_issue_types',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('company_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('icon', sa.String(), nullable=True),
        sa.Column('color', sa.String(7), nullable=False, server_default='#6366f1'),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('is_default', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('position', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_ticket_issue_types_id'), 'ticket_issue_types', ['id'], unique=False)
    op.create_index(op.f('ix_ticket_issue_types_company_id'), 'ticket_issue_types', ['company_id'], unique=False)

    # --- ticket_projects ---
    op.create_table(
        'ticket_projects',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('company_id', sa.Integer(), nullable=False),
        sa.Column('created_by_id', sa.Integer(), nullable=True),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('key', sa.String(10), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('icon', sa.String(), nullable=True),
        sa.Column('color', sa.String(7), nullable=True, server_default='#6366f1'),
        sa.Column('default_workflow_id', sa.Integer(), nullable=True),
        sa.Column('ticket_counter', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id']),
        sa.ForeignKeyConstraint(['created_by_id'], ['users.id']),
        sa.ForeignKeyConstraint(['default_workflow_id'], ['ticket_workflows.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_ticket_projects_id'), 'ticket_projects', ['id'], unique=False)
    op.create_index(op.f('ix_ticket_projects_company_id'), 'ticket_projects', ['company_id'], unique=False)
    op.create_index(op.f('ix_ticket_projects_name'), 'ticket_projects', ['name'], unique=False)
    op.create_index(op.f('ix_ticket_projects_key'), 'ticket_projects', ['key'], unique=False)

    # --- ticket_project_members ---
    op.create_table(
        'ticket_project_members',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('project_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('role', sa.String(), nullable=False, server_default='member'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['project_id'], ['ticket_projects.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_ticket_project_members_id'), 'ticket_project_members', ['id'], unique=False)
    op.create_index(op.f('ix_ticket_project_members_project_id'), 'ticket_project_members', ['project_id'], unique=False)
    op.create_index(op.f('ix_ticket_project_members_user_id'), 'ticket_project_members', ['user_id'], unique=False)

    # --- tickets ---
    # Note: sprint_id column is added in ceaff61e3fda (next migration)
    op.create_table(
        'tickets',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('company_id', sa.Integer(), nullable=False),
        sa.Column('project_id', sa.Integer(), nullable=False),
        sa.Column('ticket_number', sa.String(), nullable=False),
        sa.Column('title', sa.String(), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('issue_type_id', sa.Integer(), nullable=True),
        sa.Column('status_id', sa.Integer(), nullable=True),
        sa.Column('priority', sa.Enum('critical', 'high', 'medium', 'low', 'none', name='ticketpriority'), nullable=False, server_default='medium'),
        sa.Column('assignee_id', sa.Integer(), nullable=True),
        sa.Column('reporter_id', sa.Integer(), nullable=True),
        sa.Column('parent_id', sa.Integer(), nullable=True),
        sa.Column('labels', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('due_date', sa.DateTime(), nullable=True),
        sa.Column('start_date', sa.DateTime(), nullable=True),
        sa.Column('resolved_at', sa.DateTime(), nullable=True),
        sa.Column('closed_at', sa.DateTime(), nullable=True),
        sa.Column('story_points', sa.Float(), nullable=True),
        sa.Column('time_estimate', sa.Integer(), nullable=True),
        sa.Column('time_spent', sa.Integer(), nullable=True),
        sa.Column('contact_id', sa.Integer(), nullable=True),
        sa.Column('account_id', sa.Integer(), nullable=True),
        sa.Column('deal_id', sa.Integer(), nullable=True),
        sa.Column('custom_fields', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('position', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id']),
        sa.ForeignKeyConstraint(['project_id'], ['ticket_projects.id']),
        sa.ForeignKeyConstraint(['issue_type_id'], ['ticket_issue_types.id']),
        sa.ForeignKeyConstraint(['status_id'], ['ticket_statuses.id']),
        sa.ForeignKeyConstraint(['assignee_id'], ['users.id']),
        sa.ForeignKeyConstraint(['reporter_id'], ['users.id']),
        sa.ForeignKeyConstraint(['parent_id'], ['tickets.id']),
        sa.ForeignKeyConstraint(['contact_id'], ['contacts.id']),
        sa.ForeignKeyConstraint(['account_id'], ['accounts.id']),
        sa.ForeignKeyConstraint(['deal_id'], ['deals.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_tickets_id'), 'tickets', ['id'], unique=False)
    op.create_index(op.f('ix_tickets_company_id'), 'tickets', ['company_id'], unique=False)
    op.create_index(op.f('ix_tickets_project_id'), 'tickets', ['project_id'], unique=False)
    op.create_index(op.f('ix_tickets_ticket_number'), 'tickets', ['ticket_number'], unique=False)
    op.create_index(op.f('ix_tickets_status_id'), 'tickets', ['status_id'], unique=False)
    op.create_index(op.f('ix_tickets_priority'), 'tickets', ['priority'], unique=False)
    op.create_index(op.f('ix_tickets_assignee_id'), 'tickets', ['assignee_id'], unique=False)
    op.create_index(op.f('ix_tickets_reporter_id'), 'tickets', ['reporter_id'], unique=False)
    op.create_index(op.f('ix_tickets_parent_id'), 'tickets', ['parent_id'], unique=False)
    op.create_index(op.f('ix_tickets_contact_id'), 'tickets', ['contact_id'], unique=False)
    op.create_index(op.f('ix_tickets_account_id'), 'tickets', ['account_id'], unique=False)
    op.create_index(op.f('ix_tickets_deal_id'), 'tickets', ['deal_id'], unique=False)

    # --- ticket_watchers (association table) ---
    op.create_table(
        'ticket_watchers',
        sa.Column('ticket_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['ticket_id'], ['tickets.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('ticket_id', 'user_id'),
    )

    # --- ticket_comments ---
    op.create_table(
        'ticket_comments',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('ticket_id', sa.Integer(), nullable=False),
        sa.Column('author_id', sa.Integer(), nullable=False),
        sa.Column('parent_id', sa.Integer(), nullable=True),
        sa.Column('body', sa.Text(), nullable=False),
        sa.Column('is_internal', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['ticket_id'], ['tickets.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['author_id'], ['users.id']),
        sa.ForeignKeyConstraint(['parent_id'], ['ticket_comments.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_ticket_comments_id'), 'ticket_comments', ['id'], unique=False)
    op.create_index(op.f('ix_ticket_comments_ticket_id'), 'ticket_comments', ['ticket_id'], unique=False)

    # --- ticket_attachments ---
    op.create_table(
        'ticket_attachments',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('ticket_id', sa.Integer(), nullable=False),
        sa.Column('uploaded_by_id', sa.Integer(), nullable=False),
        sa.Column('file_name', sa.String(), nullable=False),
        sa.Column('file_size', sa.Integer(), nullable=True),
        sa.Column('mime_type', sa.String(), nullable=True),
        sa.Column('file_url', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['ticket_id'], ['tickets.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['uploaded_by_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_ticket_attachments_id'), 'ticket_attachments', ['id'], unique=False)
    op.create_index(op.f('ix_ticket_attachments_ticket_id'), 'ticket_attachments', ['ticket_id'], unique=False)

    # --- ticket_activities ---
    op.create_table(
        'ticket_activities',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('ticket_id', sa.Integer(), nullable=False),
        sa.Column('actor_id', sa.Integer(), nullable=True),
        sa.Column('action', sa.Enum(
            'created', 'updated', 'transitioned', 'commented', 'assigned',
            'attachment_added', 'attachment_removed', 'linked', 'unlinked', 'watcher_added',
            name='ticketactivityaction'
        ), nullable=False),
        sa.Column('field_name', sa.String(), nullable=True),
        sa.Column('old_value', sa.Text(), nullable=True),
        sa.Column('new_value', sa.Text(), nullable=True),
        sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['ticket_id'], ['tickets.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['actor_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_ticket_activities_id'), 'ticket_activities', ['id'], unique=False)
    op.create_index(op.f('ix_ticket_activities_ticket_id'), 'ticket_activities', ['ticket_id'], unique=False)

    # --- ticket_links ---
    op.create_table(
        'ticket_links',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('source_ticket_id', sa.Integer(), nullable=False),
        sa.Column('target_ticket_id', sa.Integer(), nullable=False),
        sa.Column('link_type', sa.Enum(
            'blocks', 'is_blocked_by', 'duplicates', 'is_duplicated_by', 'relates_to', 'clones',
            name='ticketlinktype'
        ), nullable=False),
        sa.Column('created_by_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['source_ticket_id'], ['tickets.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['target_ticket_id'], ['tickets.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['created_by_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_ticket_links_id'), 'ticket_links', ['id'], unique=False)
    op.create_index(op.f('ix_ticket_links_source_ticket_id'), 'ticket_links', ['source_ticket_id'], unique=False)
    op.create_index(op.f('ix_ticket_links_target_ticket_id'), 'ticket_links', ['target_ticket_id'], unique=False)


def downgrade() -> None:
    op.drop_table('ticket_links')
    op.drop_table('ticket_activities')
    op.drop_table('ticket_attachments')
    op.drop_table('ticket_comments')
    op.drop_table('ticket_watchers')
    op.drop_table('tickets')
    op.drop_table('ticket_project_members')
    op.drop_table('ticket_projects')
    op.drop_table('ticket_issue_types')
    op.drop_table('ticket_transitions')
    op.drop_table('ticket_statuses')
    op.drop_table('ticket_workflows')

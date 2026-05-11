"""crm_workflow_status

Revision ID: b3c7e9f21a04
Revises: fa04c105ca5d
Create Date: 2026-05-09 12:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'b3c7e9f21a04'
down_revision: Union[str, Sequence[str], None] = 'fa04c105ca5d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # entity_type on workflows ("lead" | "deal" | "contact" | None)
    op.add_column('ticket_workflows', sa.Column('entity_type', sa.String(), nullable=True))
    op.create_index('ix_ticket_workflows_entity_type', 'ticket_workflows', ['entity_type'])

    # Leads — workflow_id + status_id
    op.add_column('leads', sa.Column('workflow_id', sa.Integer(), nullable=True))
    op.add_column('leads', sa.Column('status_id', sa.Integer(), nullable=True))
    op.create_foreign_key('fk_leads_workflow_id', 'leads', 'ticket_workflows', ['workflow_id'], ['id'], ondelete='SET NULL')
    op.create_foreign_key('fk_leads_status_id', 'leads', 'ticket_statuses', ['status_id'], ['id'], ondelete='SET NULL')
    op.create_index('ix_leads_workflow_id', 'leads', ['workflow_id'])
    op.create_index('ix_leads_status_id', 'leads', ['status_id'])
    # Make stage nullable (was NOT NULL)
    op.alter_column('leads', 'stage', nullable=True)
    op.alter_column('leads', 'previous_stage', nullable=True)

    # Deals — workflow_id + status_id
    op.add_column('deals', sa.Column('workflow_id', sa.Integer(), nullable=True))
    op.add_column('deals', sa.Column('status_id', sa.Integer(), nullable=True))
    op.create_foreign_key('fk_deals_workflow_id', 'deals', 'ticket_workflows', ['workflow_id'], ['id'], ondelete='SET NULL')
    op.create_foreign_key('fk_deals_status_id', 'deals', 'ticket_statuses', ['status_id'], ['id'], ondelete='SET NULL')
    op.create_index('ix_deals_workflow_id', 'deals', ['workflow_id'])
    op.create_index('ix_deals_status_id', 'deals', ['status_id'])

    # Contacts — workflow_id + status_id
    op.add_column('contacts', sa.Column('workflow_id', sa.Integer(), nullable=True))
    op.add_column('contacts', sa.Column('status_id', sa.Integer(), nullable=True))
    op.create_foreign_key('fk_contacts_workflow_id', 'contacts', 'ticket_workflows', ['workflow_id'], ['id'], ondelete='SET NULL')
    op.create_foreign_key('fk_contacts_status_id', 'contacts', 'ticket_statuses', ['status_id'], ['id'], ondelete='SET NULL')
    op.create_index('ix_contacts_workflow_id', 'contacts', ['workflow_id'])
    op.create_index('ix_contacts_status_id', 'contacts', ['status_id'])
    # Make lifecycle_stage nullable
    op.alter_column('contacts', 'lifecycle_stage', nullable=True)


def downgrade() -> None:
    op.drop_index('ix_contacts_status_id', 'contacts')
    op.drop_index('ix_contacts_workflow_id', 'contacts')
    op.drop_constraint('fk_contacts_status_id', 'contacts', type_='foreignkey')
    op.drop_constraint('fk_contacts_workflow_id', 'contacts', type_='foreignkey')
    op.drop_column('contacts', 'status_id')
    op.drop_column('contacts', 'workflow_id')

    op.drop_index('ix_deals_status_id', 'deals')
    op.drop_index('ix_deals_workflow_id', 'deals')
    op.drop_constraint('fk_deals_status_id', 'deals', type_='foreignkey')
    op.drop_constraint('fk_deals_workflow_id', 'deals', type_='foreignkey')
    op.drop_column('deals', 'status_id')
    op.drop_column('deals', 'workflow_id')

    op.drop_index('ix_leads_status_id', 'leads')
    op.drop_index('ix_leads_workflow_id', 'leads')
    op.drop_constraint('fk_leads_status_id', 'leads', type_='foreignkey')
    op.drop_constraint('fk_leads_workflow_id', 'leads', type_='foreignkey')
    op.drop_column('leads', 'status_id')
    op.drop_column('leads', 'workflow_id')

    op.drop_index('ix_ticket_workflows_entity_type', 'ticket_workflows')
    op.drop_column('ticket_workflows', 'entity_type')

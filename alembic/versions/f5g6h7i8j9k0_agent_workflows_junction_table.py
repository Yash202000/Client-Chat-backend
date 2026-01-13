"""Add agent_workflows junction table for many-to-many relationship

Revision ID: f5g6h7i8j9k0
Revises: e4f5g6h7i8j9
Create Date: 2026-01-12

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'f5g6h7i8j9k0'
down_revision = 'e4f5g6h7i8j9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create the junction table for many-to-many relationship
    op.create_table(
        'agent_workflows',
        sa.Column('agent_id', sa.Integer(), sa.ForeignKey('agents.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('workflow_id', sa.Integer(), sa.ForeignKey('workflows.id', ondelete='CASCADE'), primary_key=True)
    )

    # Migrate existing data: copy agent_id relationships to junction table
    op.execute("""
        INSERT INTO agent_workflows (agent_id, workflow_id)
        SELECT agent_id, id FROM workflows WHERE agent_id IS NOT NULL
    """)

    # Drop the agent_id column from workflows table
    op.drop_constraint('workflows_agent_id_fkey', 'workflows', type_='foreignkey')
    op.drop_column('workflows', 'agent_id')


def downgrade() -> None:
    # Add back the agent_id column
    op.add_column('workflows', sa.Column('agent_id', sa.Integer(), nullable=True))
    op.create_foreign_key('workflows_agent_id_fkey', 'workflows', 'agents', ['agent_id'], ['id'])

    # Migrate data back: take first agent_id from junction table
    op.execute("""
        UPDATE workflows w
        SET agent_id = (
            SELECT agent_id FROM agent_workflows aw
            WHERE aw.workflow_id = w.id
            LIMIT 1
        )
    """)

    # Drop the junction table
    op.drop_table('agent_workflows')

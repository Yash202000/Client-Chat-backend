"""crm_workflow_limits — max_contacts, max_leads, max_workflows, max_campaigns per plan

Revision ID: s4t5u6v7w8x9
Revises: r3s4t5u6v7w8
Create Date: 2026-06-08
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine.reflection import Inspector

revision = 's4t5u6v7w8x9'
down_revision = 'r3s4t5u6v7w8'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = Inspector.from_engine(bind)
    plan_cols = {c['name'] for c in inspector.get_columns('subscription_plans')}
    for col in ('max_contacts', 'max_leads', 'max_workflows', 'max_campaigns'):
        if col not in plan_cols:
            op.add_column('subscription_plans', sa.Column(col, sa.Integer(), nullable=True))


def downgrade():
    for col in ('max_campaigns', 'max_workflows', 'max_leads', 'max_contacts'):
        op.drop_column('subscription_plans', col)

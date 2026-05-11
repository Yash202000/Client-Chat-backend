"""drop role from user_node_assignments

Revision ID: c4d5e6f7a8b9
Revises: b2c3d4e5f6a7
Create Date: 2026-05-10

"""
from alembic import op
import sqlalchemy as sa

revision = 'c4d5e6f7a8b9'
down_revision = 'b2c3d4e5f6a7'
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint('uq_user_node_role', 'user_node_assignments', type_='unique')
    op.drop_column('user_node_assignments', 'role')
    op.create_unique_constraint('uq_user_node', 'user_node_assignments', ['user_id', 'node_id'])


def downgrade():
    op.drop_constraint('uq_user_node', 'user_node_assignments', type_='unique')
    op.add_column('user_node_assignments', sa.Column('role', sa.String(), server_default='agent', nullable=False))
    op.create_unique_constraint('uq_user_node_role', 'user_node_assignments', ['user_id', 'node_id', 'role'])

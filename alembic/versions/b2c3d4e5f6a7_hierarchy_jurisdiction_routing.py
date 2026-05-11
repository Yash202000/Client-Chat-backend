"""hierarchy_jurisdiction_routing

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-05-10 12:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── hierarchy_types ──────────────────────────────────────────────────────
    op.create_table(
        'hierarchy_types',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('company_id', sa.Integer(), sa.ForeignKey('companies.id'), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('description', sa.String(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('position', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_hierarchy_types_company_id', 'hierarchy_types', ['company_id'])

    # ── hierarchy_nodes ──────────────────────────────────────────────────────
    op.create_table(
        'hierarchy_nodes',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('company_id', sa.Integer(), sa.ForeignKey('companies.id'), nullable=False),
        sa.Column('type_id', sa.Integer(), sa.ForeignKey('hierarchy_types.id', ondelete='CASCADE'), nullable=False),
        sa.Column('parent_id', sa.Integer(), sa.ForeignKey('hierarchy_nodes.id', ondelete='CASCADE'), nullable=True),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('code', sa.String(), nullable=False),
        sa.Column('path', sa.String(), nullable=False),
        sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('position', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('company_id', 'type_id', 'code', name='uq_hierarchy_node_code'),
    )
    op.create_index('ix_hierarchy_nodes_company_id', 'hierarchy_nodes', ['company_id'])
    op.create_index('ix_hierarchy_nodes_type_id', 'hierarchy_nodes', ['type_id'])
    op.create_index('ix_hierarchy_nodes_parent_id', 'hierarchy_nodes', ['parent_id'])
    op.create_index('ix_hierarchy_nodes_path', 'hierarchy_nodes', ['path'])

    # ── user_node_assignments ────────────────────────────────────────────────
    op.create_table(
        'user_node_assignments',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('company_id', sa.Integer(), sa.ForeignKey('companies.id'), nullable=False),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('node_id', sa.Integer(), sa.ForeignKey('hierarchy_nodes.id', ondelete='CASCADE'), nullable=False),
        sa.Column('role', sa.String(), nullable=False, server_default='agent'),
        sa.Column('team_id', sa.Integer(), sa.ForeignKey('teams.id', ondelete='SET NULL'), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'node_id', 'role', name='uq_user_node_role'),
    )
    op.create_index('ix_user_node_assignments_user_id', 'user_node_assignments', ['user_id'])
    op.create_index('ix_user_node_assignments_node_id', 'user_node_assignments', ['node_id'])
    op.create_index('ix_user_node_assignments_company_id', 'user_node_assignments', ['company_id'])

    # ── team_node_assignments ────────────────────────────────────────────────
    op.create_table(
        'team_node_assignments',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('company_id', sa.Integer(), sa.ForeignKey('companies.id'), nullable=False),
        sa.Column('team_id', sa.Integer(), sa.ForeignKey('teams.id', ondelete='CASCADE'), nullable=False),
        sa.Column('node_id', sa.Integer(), sa.ForeignKey('hierarchy_nodes.id', ondelete='CASCADE'), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('team_id', 'node_id', name='uq_team_node'),
    )
    op.create_index('ix_team_node_assignments_team_id', 'team_node_assignments', ['team_id'])
    op.create_index('ix_team_node_assignments_company_id', 'team_node_assignments', ['company_id'])


def downgrade() -> None:
    op.drop_table('team_node_assignments')
    op.drop_table('user_node_assignments')
    op.drop_table('hierarchy_nodes')
    op.drop_table('hierarchy_types')

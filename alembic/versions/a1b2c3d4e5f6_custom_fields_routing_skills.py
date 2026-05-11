"""custom_fields_routing_rules_agent_skills

Revision ID: a1b2c3d4e5f6
Revises: fa04c105ca5d
Create Date: 2026-05-09 10:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = ('fa04c105ca5d', 'b3c7e9f21a04')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── custom_field_definitions ─────────────────────────────────────────────
    op.create_table(
        'custom_field_definitions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('company_id', sa.Integer(), sa.ForeignKey('companies.id'), nullable=False),
        sa.Column('entity_type', sa.String(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('label', sa.String(), nullable=False),
        sa.Column('field_type', sa.String(), nullable=False, server_default='text'),
        sa.Column('options', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('required', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('default_value', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('position', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('group_name', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_custom_field_definitions_company_id', 'custom_field_definitions', ['company_id'])
    op.create_index('ix_custom_field_definitions_entity_type', 'custom_field_definitions', ['entity_type'])

    # ── routing_rules ────────────────────────────────────────────────────────
    op.create_table(
        'routing_rules',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('company_id', sa.Integer(), sa.ForeignKey('companies.id'), nullable=False),
        sa.Column('entity_type', sa.String(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('priority', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('trigger', sa.String(), nullable=False, server_default='on_create'),
        sa.Column('trigger_transition_id', sa.Integer(), sa.ForeignKey('ticket_transitions.id'), nullable=True),
        sa.Column('conditions', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('action_type', sa.String(), nullable=False, server_default='assign_to_user'),
        sa.Column('action_config', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_routing_rules_company_id', 'routing_rules', ['company_id'])
    op.create_index('ix_routing_rules_entity_type', 'routing_rules', ['entity_type'])

    # ── routing_round_robin_state ────────────────────────────────────────────
    op.create_table(
        'routing_round_robin_state',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('rule_id', sa.Integer(), sa.ForeignKey('routing_rules.id'), nullable=False),
        sa.Column('last_assigned_user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('last_assigned_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('rule_id'),
    )
    op.create_index('ix_routing_round_robin_state_rule_id', 'routing_round_robin_state', ['rule_id'])

    # ── team_memberships: add skills ─────────────────────────────────────────
    op.add_column('team_memberships',
        sa.Column('skills', postgresql.JSONB(astext_type=sa.Text()), nullable=True)
    )


def downgrade() -> None:
    op.drop_column('team_memberships', 'skills')
    op.drop_table('routing_round_robin_state')
    op.drop_table('routing_rules')
    op.drop_table('custom_field_definitions')

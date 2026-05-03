"""add campaign_sequence_triggers table

Revision ID: d0e1f2a3b4c5
Revises: c9d0e1f2a3b4
Create Date: 2026-05-02

"""
from alembic import op
import sqlalchemy as sa

revision = 'd0e1f2a3b4c5'
down_revision = 'c9d0e1f2a3b4'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'campaign_sequence_triggers',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('campaign_id', sa.Integer(), sa.ForeignKey('campaigns.id'), nullable=False),
        sa.Column('sequence_id', sa.Integer(), sa.ForeignKey('sequences.id'), nullable=False),
        sa.Column('trigger_condition', sa.String(), nullable=False),
        sa.Column('delay_hours', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('last_fired_at', sa.DateTime(), nullable=True),
        sa.Column('enrolled_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_campaign_sequence_triggers_id', 'campaign_sequence_triggers', ['id'])
    op.create_index('ix_campaign_sequence_triggers_campaign_id', 'campaign_sequence_triggers', ['campaign_id'])
    op.create_index('ix_campaign_sequence_triggers_sequence_id', 'campaign_sequence_triggers', ['sequence_id'])


def downgrade():
    op.drop_table('campaign_sequence_triggers')

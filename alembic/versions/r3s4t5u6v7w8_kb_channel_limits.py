"""kb_channel_limits — max_knowledge_bases and max_channels per plan

Revision ID: r3s4t5u6v7w8
Revises: q2r3s4t5u6v7
Create Date: 2026-06-08
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine.reflection import Inspector

revision = 'r3s4t5u6v7w8'
down_revision = 'q2r3s4t5u6v7'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = Inspector.from_engine(bind)
    plan_cols = {c['name'] for c in inspector.get_columns('subscription_plans')}
    if 'max_knowledge_bases' not in plan_cols:
        op.add_column('subscription_plans', sa.Column('max_knowledge_bases', sa.Integer(), nullable=True))
    if 'max_channels' not in plan_cols:
        op.add_column('subscription_plans', sa.Column('max_channels', sa.Integer(), nullable=True))


def downgrade():
    op.drop_column('subscription_plans', 'max_channels')
    op.drop_column('subscription_plans', 'max_knowledge_bases')

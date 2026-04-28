"""Add calendar_events table

Revision ID: m2n3o4p5q6r7
Revises: l1m2n3o4p5q6
Create Date: 2026-04-28
"""
from alembic import op
import sqlalchemy as sa

revision = 'm2n3o4p5q6r7'
down_revision = 'l1m2n3o4p5q6'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'calendar_events',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('company_id', sa.Integer(), sa.ForeignKey('companies.id'), nullable=False),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('title', sa.String(255), nullable=False),
        sa.Column('event_type', sa.String(50), nullable=True, server_default='meeting'),
        sa.Column('start_time', sa.DateTime(timezone=True), nullable=False),
        sa.Column('end_time', sa.DateTime(timezone=True), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('attendees', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_calendar_events_id', 'calendar_events', ['id'], unique=False)
    op.create_index('ix_calendar_events_company_id', 'calendar_events', ['company_id'], unique=False)
    op.create_index('ix_calendar_events_user_id', 'calendar_events', ['user_id'], unique=False)


def downgrade():
    op.drop_index('ix_calendar_events_user_id', table_name='calendar_events')
    op.drop_index('ix_calendar_events_company_id', table_name='calendar_events')
    op.drop_index('ix_calendar_events_id', table_name='calendar_events')
    op.drop_table('calendar_events')

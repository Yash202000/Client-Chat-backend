"""calendar: add livekit_room_name, recurrence fields, parent_event_id

Revision ID: p5q6r7s8t9u0
Revises: o4p5q6r7s8t9
Create Date: 2026-04-28
"""
from alembic import op
import sqlalchemy as sa

revision = 'p5q6r7s8t9u0'
down_revision = 'o4p5q6r7s8t9'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('calendar_events', sa.Column('livekit_room_name', sa.String(255), nullable=True))
    op.add_column('calendar_events', sa.Column('recurrence_rule', sa.String(50), nullable=True))
    op.add_column('calendar_events', sa.Column('recurrence_interval', sa.Integer(), nullable=True, server_default='1'))
    op.add_column('calendar_events', sa.Column('recurrence_end_date', sa.DateTime(timezone=True), nullable=True))
    op.add_column('calendar_events', sa.Column('parent_event_id', sa.Integer(), nullable=True))
    op.create_foreign_key(
        'fk_calendar_events_parent',
        'calendar_events', 'calendar_events',
        ['parent_event_id'], ['id'],
        ondelete='SET NULL',
    )


def downgrade():
    op.drop_constraint('fk_calendar_events_parent', 'calendar_events', type_='foreignkey')
    op.drop_column('calendar_events', 'parent_event_id')
    op.drop_column('calendar_events', 'recurrence_end_date')
    op.drop_column('calendar_events', 'recurrence_interval')
    op.drop_column('calendar_events', 'recurrence_rule')
    op.drop_column('calendar_events', 'livekit_room_name')

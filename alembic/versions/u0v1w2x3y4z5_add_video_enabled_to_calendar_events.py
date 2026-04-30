"""add video_enabled to calendar_events

Revision ID: u0v1w2x3y4z5
Revises: t9u0v1w2x3y4
Create Date: 2026-04-30

"""
from alembic import op
import sqlalchemy as sa

revision = 'u0v1w2x3y4z5'
down_revision = 't9u0v1w2x3y4'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('calendar_events', sa.Column('video_enabled', sa.Boolean(), nullable=True))
    # Backfill: any event that already has a livekit_room_name had video enabled
    op.execute("UPDATE calendar_events SET video_enabled = TRUE WHERE livekit_room_name IS NOT NULL")


def downgrade():
    op.drop_column('calendar_events', 'video_enabled')

"""Phase 2 & 3 voice features: skills routing, voicemail, CSAT, queue overflow

Revision ID: l1m2n3o4p5q6
Revises: k0l1m2n3o4p5
Create Date: 2026-04-26
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = 'l1m2n3o4p5q6'
down_revision = 'k0l1m2n3o4p5'
branch_labels = None
depends_on = None


def upgrade():
    # users.skills — JSON array of skill tags
    op.add_column('users', sa.Column('skills', JSONB(), nullable=True))

    # call_queue_entries — skills routing + voicemail/overflow
    op.add_column('call_queue_entries', sa.Column('required_skill', sa.String(), nullable=True))
    op.add_column('call_queue_entries', sa.Column('voicemail_url', sa.String(), nullable=True))
    op.add_column('call_queue_entries', sa.Column('overflow_at', sa.DateTime(), nullable=True))

    # voice_calls — CSAT
    op.add_column('voice_calls', sa.Column('csat_score', sa.Integer(), nullable=True))
    op.add_column('voice_calls', sa.Column('csat_sent_at', sa.DateTime(), nullable=True))


def downgrade():
    op.drop_column('voice_calls', 'csat_sent_at')
    op.drop_column('voice_calls', 'csat_score')
    op.drop_column('call_queue_entries', 'overflow_at')
    op.drop_column('call_queue_entries', 'voicemail_url')
    op.drop_column('call_queue_entries', 'required_skill')
    op.drop_column('users', 'skills')

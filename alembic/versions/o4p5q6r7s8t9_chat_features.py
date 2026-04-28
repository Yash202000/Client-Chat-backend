"""Add chat features: pinned messages, message reads, scheduled messages, user status

Revision ID: o4p5q6r7s8t9
Revises: n3o4p5q6r7s8
Create Date: 2026-04-28 00:00:00
"""
from alembic import op
import sqlalchemy as sa

revision = 'o4p5q6r7s8t9'
down_revision = 'n3o4p5q6r7s8'
branch_labels = None
depends_on = None


def upgrade():
    # Add scheduled_at to internal_chat_messages
    op.add_column('internal_chat_messages',
        sa.Column('scheduled_at', sa.DateTime(timezone=True), nullable=True))

    # Add status fields to users
    op.add_column('users', sa.Column('status_message', sa.String(255), nullable=True))
    op.add_column('users', sa.Column('dnd_until', sa.DateTime(timezone=True), nullable=True))

    # Create pinned_messages table
    op.create_table(
        'pinned_messages',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('channel_id', sa.Integer(),
                  sa.ForeignKey('chat_channels.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('message_id', sa.Integer(),
                  sa.ForeignKey('internal_chat_messages.id', ondelete='CASCADE'), nullable=False),
        sa.Column('pinned_by_user_id', sa.Integer(),
                  sa.ForeignKey('users.id'), nullable=False),
        sa.Column('pinned_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint('channel_id', 'message_id', name='uq_pinned_msg'),
    )

    # Create message_reads table
    op.create_table(
        'message_reads',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('message_id', sa.Integer(),
                  sa.ForeignKey('internal_chat_messages.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('user_id', sa.Integer(),
                  sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('read_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint('message_id', 'user_id', name='uq_message_read'),
    )


def downgrade():
    op.drop_table('message_reads')
    op.drop_table('pinned_messages')
    op.drop_column('users', 'dnd_until')
    op.drop_column('users', 'status_message')
    op.drop_column('internal_chat_messages', 'scheduled_at')

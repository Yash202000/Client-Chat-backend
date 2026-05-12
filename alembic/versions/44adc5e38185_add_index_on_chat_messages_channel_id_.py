"""add index on chat messages channel_id created_at

Revision ID: 44adc5e38185
Revises: h3i4j5k6l7m8
Create Date: 2026-05-13 00:27:04.768661

"""
from typing import Sequence, Union

from alembic import op

revision: str = '44adc5e38185'
down_revision: Union[str, Sequence[str], None] = 'h3i4j5k6l7m8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index('ix_chat_messages_channel_created', 'internal_chat_messages', ['channel_id', 'created_at'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_chat_messages_channel_created', table_name='internal_chat_messages')

"""add ticket co-assignees

Revision ID: f1a2b3c4d5e6
Revises: ceaff61e3fda
Create Date: 2026-05-11
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'f1a2b3c4d5e6'
down_revision: Union[str, Sequence[str], None] = 'd5e6f7a8b9c0'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS ticket_co_assignees (
            ticket_id INTEGER NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
            user_id   INTEGER NOT NULL REFERENCES users(id)   ON DELETE CASCADE,
            PRIMARY KEY (ticket_id, user_id)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_ticket_co_assignees_ticket_id ON ticket_co_assignees (ticket_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_ticket_co_assignees_user_id   ON ticket_co_assignees (user_id)")


def downgrade() -> None:
    op.drop_index('ix_ticket_co_assignees_user_id',   table_name='ticket_co_assignees')
    op.drop_index('ix_ticket_co_assignees_ticket_id', table_name='ticket_co_assignees')
    op.drop_table('ticket_co_assignees')

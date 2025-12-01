"""add_template_id_to_campaign_messages

Revision ID: f1a2b3c4d5e6
Revises: ec0f5ffb28aa
Create Date: 2025-11-30 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f1a2b3c4d5e6'
down_revision: Union[str, Sequence[str], None] = 'ec0f5ffb28aa'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add template_id column to campaign_messages table."""
    op.add_column('campaign_messages', sa.Column('template_id', sa.Integer(), nullable=True))
    op.create_foreign_key(
        'fk_campaign_messages_template_id',
        'campaign_messages', 'templates',
        ['template_id'], ['id'],
        ondelete='SET NULL'
    )


def downgrade() -> None:
    """Remove template_id column from campaign_messages table."""
    op.drop_constraint('fk_campaign_messages_template_id', 'campaign_messages', type_='foreignkey')
    op.drop_column('campaign_messages', 'template_id')

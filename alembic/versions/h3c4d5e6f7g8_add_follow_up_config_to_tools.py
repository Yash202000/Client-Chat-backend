"""Add follow_up_config to tools

Revision ID: h3c4d5e6f7g8
Revises: g2b3c4d5e6f7
Create Date: 2024-12-02

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'h3c4d5e6f7g8'
down_revision: Union[str, None] = 'g2b3c4d5e6f7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add follow_up_config column to tools table
    op.add_column('tools', sa.Column('follow_up_config', sa.JSON(), nullable=True))


def downgrade() -> None:
    # Remove follow_up_config column from tools table
    op.drop_column('tools', 'follow_up_config')

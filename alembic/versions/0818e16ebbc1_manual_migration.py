"""manual migration

Revision ID: 0818e16ebbc1
Revises: c9d0e1f2g3h4
Create Date: 2026-01-05 13:48:14.867472

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0818e16ebbc1'
down_revision: Union[str, Sequence[str], None] = 'c9d0e1f2g3h4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass

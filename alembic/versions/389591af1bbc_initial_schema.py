"""initial_schema

Revision ID: 389591af1bbc
Revises:
Create Date: 2026-05-04 14:41:29.154015

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '389591af1bbc'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
    import app.models  # noqa — registers all models on Base.metadata
    from app.core.database import Base
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind, checkfirst=True)


def downgrade() -> None:
    pass

"""init modals

Revision ID: 2426d72552f6
Revises:
Create Date: 2025-10-19 20:07:22.941372

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '2426d72552f6'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema - Use Base.metadata.create_all() approach."""
    # Import Base to trigger all model registrations
    from app.core.database import Base
    from app import models  # Import all models

    # Create all tables from metadata
    # This will use the current model definitions including intent_config
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    """Downgrade schema."""
    # Drop all tables
    from app.core.database import Base
    from app import models

    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)

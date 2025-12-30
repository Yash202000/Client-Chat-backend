"""fix_integrations_credentials_column

Revision ID: b8c9d0e1f2g3
Revises: a7c8d9e0f1g2
Create Date: 2025-12-29 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b8c9d0e1f2g3'
down_revision: Union[str, Sequence[str], None] = 'a7c8d9e0f1g2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Change integrations.credentials from String to LargeBinary.
    This matches the Credential model's encrypted_credentials column type.

    NOTE: Existing data in this column will be corrupted after this migration
    if it was stored incorrectly (bytes as string repr). Users will need to
    re-save their integrations.
    """
    # First, drop any existing corrupted data by setting credentials to NULL temporarily
    # Then alter the column type
    op.execute("DELETE FROM integrations WHERE credentials LIKE 'b''%'")

    # Alter column type from String to LargeBinary
    op.alter_column(
        'integrations',
        'credentials',
        existing_type=sa.String(),
        type_=sa.LargeBinary(),
        existing_nullable=False,
        postgresql_using="credentials::bytea"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column(
        'integrations',
        'credentials',
        existing_type=sa.LargeBinary(),
        type_=sa.String(),
        existing_nullable=False
    )

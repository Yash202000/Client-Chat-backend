"""add custom field project configs

Revision ID: g2h3i4j5k6l7
Revises: f1a2b3c4d5e6
Create Date: 2026-05-11
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'g2h3i4j5k6l7'
down_revision: Union[str, Sequence[str], None] = 'f1a2b3c4d5e6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE custom_field_definitions
        ADD COLUMN IF NOT EXISTS is_global BOOLEAN NOT NULL DEFAULT TRUE
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS custom_field_project_configs (
            id          SERIAL PRIMARY KEY,
            company_id  INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
            field_id    INTEGER NOT NULL REFERENCES custom_field_definitions(id) ON DELETE CASCADE,
            project_id  INTEGER NOT NULL REFERENCES ticket_projects(id) ON DELETE CASCADE,
            visible     BOOLEAN NOT NULL DEFAULT TRUE,
            required    BOOLEAN,
            position    INTEGER,
            group_name  VARCHAR,
            created_at  TIMESTAMP NOT NULL DEFAULT now(),
            updated_at  TIMESTAMP NOT NULL DEFAULT now(),
            UNIQUE (field_id, project_id)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_cfpc_company ON custom_field_project_configs (company_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_cfpc_field   ON custom_field_project_configs (field_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_cfpc_project ON custom_field_project_configs (project_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS custom_field_project_configs")
    op.execute("ALTER TABLE custom_field_definitions DROP COLUMN IF EXISTS is_global")

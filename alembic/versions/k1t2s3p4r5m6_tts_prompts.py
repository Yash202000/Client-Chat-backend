"""Pre-generated speech for fixed phone prompts (tts_prompts)

Revision ID: k1t2s3p4r5m6
Revises: j0k1a2m3l4o5
Create Date: 2026-10-14 00:00:03

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'k1t2s3p4r5m6'
down_revision: Union[str, Sequence[str], None] = 'j0k1a2m3l4o5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tts_prompts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("key", sa.String(64), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("voice", sa.String(64), nullable=False),
        sa.Column("language", sa.String(16), nullable=True),
        sa.Column("object_key", sa.String(255), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("company_id", "key", name="uq_tts_prompts_company_key"),
    )
    op.create_index("ix_tts_prompts_company_id", "tts_prompts", ["company_id"])


def downgrade() -> None:
    op.drop_index("ix_tts_prompts_company_id", table_name="tts_prompts")
    op.drop_table("tts_prompts")

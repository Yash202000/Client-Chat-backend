"""social_widgets table

Revision ID: m8n9o0p1q2r3
Revises: l7m8n9o0p1q2
Create Date: 2026-06-03
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine.reflection import Inspector

revision = 'm8n9o0p1q2r3'
down_revision = 'l7m8n9o0p1q2'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    inspector = Inspector.from_engine(conn)
    if "social_widgets" not in inspector.get_table_names():
        op.create_table(
            "social_widgets",
            sa.Column("id", sa.Integer(), primary_key=True, index=True),
            sa.Column("widget_key", sa.String(64), unique=True, index=True, nullable=False),
            sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
            sa.Column("channel", sa.String(20), nullable=False),
            sa.Column("name", sa.String(255), nullable=False, server_default="Widget"),
            sa.Column("handle", sa.String(255), nullable=False),
            sa.Column("greeting_text", sa.String(255), server_default="Chat with us!"),
            sa.Column("subtext", sa.String(255), server_default="Typically replies within minutes"),
            sa.Column("button_label", sa.String(100), server_default="Chat now"),
            sa.Column("button_color", sa.String(20), server_default="#000000"),
            sa.Column("button_text_color", sa.String(20), server_default="#FFFFFF"),
            sa.Column("position", sa.String(20), server_default="bottom-right"),
            sa.Column("show_tooltip", sa.Boolean(), server_default=sa.true()),
            sa.Column("show_agent_avatar", sa.Boolean(), server_default=sa.false()),
            sa.Column("agent_avatar_url", sa.String(500), nullable=True),
            sa.Column("agent_name", sa.String(100), nullable=True),
            sa.Column("is_active", sa.Boolean(), server_default=sa.true()),
        )


def downgrade():
    op.drop_table("social_widgets")

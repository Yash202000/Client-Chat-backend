"""cts_links — click to social links and clicks

Revision ID: n9o0p1q2r3s4
Revises: m8n9o0p1q2r3
Create Date: 2026-06-03
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine.reflection import Inspector

revision = 'n9o0p1q2r3s4'
down_revision = 'm8n9o0p1q2r3'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = Inspector.from_engine(bind)
    existing = inspector.get_table_names()

    if 'cts_links' not in existing:
        op.create_table(
            'cts_links',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('link_key', sa.String(32), nullable=False),
            sa.Column('company_id', sa.Integer(), nullable=False),
            sa.Column('channel', sa.String(20), nullable=False),
            sa.Column('name', sa.String(255), nullable=False),
            sa.Column('handle', sa.String(255), nullable=False),
            sa.Column('prefill_message', sa.String(500), nullable=True),
            sa.Column('utm_source', sa.String(100), nullable=True),
            sa.Column('utm_medium', sa.String(100), nullable=True),
            sa.Column('utm_campaign', sa.String(100), nullable=True),
            sa.Column('utm_content', sa.String(100), nullable=True),
            sa.Column('auto_tag', sa.String(100), nullable=True),
            sa.Column('workflow_id', sa.Integer(), nullable=True),
            sa.Column('click_count', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('contact_count', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(['company_id'], ['companies.id']),
            sa.ForeignKeyConstraint(['workflow_id'], ['workflows.id']),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index('ix_cts_links_id', 'cts_links', ['id'])
        op.create_index('ix_cts_links_link_key', 'cts_links', ['link_key'], unique=True)

    if 'cts_clicks' not in existing:
        op.create_table(
            'cts_clicks',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('link_id', sa.Integer(), nullable=False),
            sa.Column('company_id', sa.Integer(), nullable=False),
            sa.Column('referrer_url', sa.String(1000), nullable=True),
            sa.Column('user_agent', sa.String(500), nullable=True),
            sa.Column('ip_address', sa.String(64), nullable=True),
            sa.Column('contact_id', sa.Integer(), nullable=True),
            sa.Column('clicked_at', sa.DateTime(), nullable=False),
            sa.Column('converted_at', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['company_id'], ['companies.id']),
            sa.ForeignKeyConstraint(['contact_id'], ['contacts.id']),
            sa.ForeignKeyConstraint(['link_id'], ['cts_links.id']),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index('ix_cts_clicks_id', 'cts_clicks', ['id'])


def downgrade():
    op.drop_table('cts_clicks')
    op.drop_table('cts_links')

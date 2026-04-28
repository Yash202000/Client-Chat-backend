"""add drive_items table

Revision ID: s8t9u0v1w2x3
Revises: r7s8t9u0v1w2
Create Date: 2026-04-29 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = 's8t9u0v1w2x3'
down_revision = 'r7s8t9u0v1w2'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'drive_items',
        sa.Column('id',         sa.Integer(),              nullable=False),
        sa.Column('company_id', sa.Integer(),              nullable=False),
        sa.Column('owner_id',   sa.Integer(),              nullable=True),
        sa.Column('parent_id',  sa.Integer(),              nullable=True),
        sa.Column('name',       sa.String(255),            nullable=False),
        sa.Column('is_folder',  sa.Boolean(),              nullable=False, server_default='false'),
        sa.Column('s3_key',     sa.String(500),            nullable=True),
        sa.Column('mime_type',  sa.String(100),            nullable=True),
        sa.Column('file_size',  sa.BigInteger(),           nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'],   ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['owner_id'],   ['users.id'],       ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['parent_id'],  ['drive_items.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_drive_items_id',         'drive_items', ['id'],         unique=False)
    op.create_index('ix_drive_items_company_id', 'drive_items', ['company_id'], unique=False)
    op.create_index('ix_drive_items_parent_id',  'drive_items', ['parent_id'],  unique=False)


def downgrade():
    op.drop_index('ix_drive_items_parent_id',  table_name='drive_items')
    op.drop_index('ix_drive_items_company_id', table_name='drive_items')
    op.drop_index('ix_drive_items_id',         table_name='drive_items')
    op.drop_table('drive_items')

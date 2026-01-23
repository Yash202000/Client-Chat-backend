"""Add CMS tables for content management

Revision ID: g6h7i8j9k0l1
Revises: f5g6h7i8j9k0
Create Date: 2026-01-13

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


# revision identifiers, used by Alembic.
revision: str = 'g6h7i8j9k0l1'
down_revision: Union[str, None] = 'f5g6h7i8j9k0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create CMS tables."""

    # 1. Create content_types table
    op.create_table(
        'content_types',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('company_id', sa.Integer(), nullable=False),
        sa.Column('knowledge_base_id', sa.Integer(), nullable=True),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('slug', sa.String(100), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('icon', sa.String(50), nullable=True),
        sa.Column('field_schema', JSONB(), nullable=False, server_default='[]'),
        sa.Column('allow_public_publish', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['knowledge_base_id'], ['knowledge_bases.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('company_id', 'slug', name='uq_content_types_company_slug')
    )
    op.create_index(op.f('ix_content_types_id'), 'content_types', ['id'], unique=False)
    op.create_index(op.f('ix_content_types_slug'), 'content_types', ['slug'], unique=False)

    # 2. Create content_items table
    op.create_table(
        'content_items',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('content_type_id', sa.Integer(), nullable=False),
        sa.Column('company_id', sa.Integer(), nullable=False),
        sa.Column('knowledge_base_id', sa.Integer(), nullable=True),
        sa.Column('data', JSONB(), nullable=False, server_default='{}'),
        sa.Column('status', sa.String(20), nullable=False, server_default='draft'),
        sa.Column('visibility', sa.String(20), nullable=False, server_default='private'),
        sa.Column('is_featured', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('download_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('rating', sa.Numeric(2, 1), nullable=True),
        sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('chroma_doc_id', sa.String(100), nullable=True),
        sa.Column('created_by', sa.Integer(), nullable=True),
        sa.Column('updated_by', sa.Integer(), nullable=True),
        sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['content_type_id'], ['content_types.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['knowledge_base_id'], ['knowledge_bases.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['updated_by'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_content_items_id'), 'content_items', ['id'], unique=False)
    op.create_index(op.f('ix_content_items_status'), 'content_items', ['status'], unique=False)
    op.create_index(op.f('ix_content_items_visibility'), 'content_items', ['visibility'], unique=False)
    op.create_index('ix_content_items_data', 'content_items', ['data'], unique=False, postgresql_using='gin')

    # 3. Create content_media table
    op.create_table(
        'content_media',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('company_id', sa.Integer(), nullable=False),
        sa.Column('filename', sa.String(255), nullable=False),
        sa.Column('original_filename', sa.String(255), nullable=True),
        sa.Column('mime_type', sa.String(100), nullable=True),
        sa.Column('file_size', sa.Integer(), nullable=True),
        sa.Column('media_type', sa.String(20), nullable=True),
        sa.Column('s3_bucket', sa.String(100), nullable=True),
        sa.Column('s3_key', sa.String(500), nullable=False),
        sa.Column('thumbnail_s3_key', sa.String(500), nullable=True),
        sa.Column('width', sa.Integer(), nullable=True),
        sa.Column('height', sa.Integer(), nullable=True),
        sa.Column('duration', sa.Integer(), nullable=True),
        sa.Column('alt_text', sa.String(255), nullable=True),
        sa.Column('caption', sa.Text(), nullable=True),
        sa.Column('usage_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('uploaded_by', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['uploaded_by'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_content_media_id'), 'content_media', ['id'], unique=False)
    op.create_index(op.f('ix_content_media_media_type'), 'content_media', ['media_type'], unique=False)

    # 4. Create content_categories table
    op.create_table(
        'content_categories',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('company_id', sa.Integer(), nullable=False),
        sa.Column('knowledge_base_id', sa.Integer(), nullable=True),
        sa.Column('parent_id', sa.Integer(), nullable=True),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('slug', sa.String(100), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('icon', sa.String(50), nullable=True),
        sa.Column('display_order', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['knowledge_base_id'], ['knowledge_bases.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['parent_id'], ['content_categories.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('company_id', 'knowledge_base_id', 'slug', name='uq_content_categories_company_kb_slug')
    )
    op.create_index(op.f('ix_content_categories_id'), 'content_categories', ['id'], unique=False)
    op.create_index(op.f('ix_content_categories_slug'), 'content_categories', ['slug'], unique=False)

    # 5. Create content_item_categories junction table (many-to-many)
    op.create_table(
        'content_item_categories',
        sa.Column('content_item_id', sa.Integer(), nullable=False),
        sa.Column('category_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['content_item_id'], ['content_items.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['category_id'], ['content_categories.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('content_item_id', 'category_id')
    )

    # 6. Create content_tags table
    op.create_table(
        'content_tags',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('company_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('slug', sa.String(100), nullable=False),
        sa.Column('color', sa.String(7), nullable=True),
        sa.Column('usage_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('company_id', 'slug', name='uq_content_tags_company_slug')
    )
    op.create_index(op.f('ix_content_tags_id'), 'content_tags', ['id'], unique=False)
    op.create_index(op.f('ix_content_tags_slug'), 'content_tags', ['slug'], unique=False)

    # 7. Create content_copies table (marketplace forking)
    op.create_table(
        'content_copies',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('original_item_id', sa.Integer(), nullable=False),
        sa.Column('original_company_id', sa.Integer(), nullable=False),
        sa.Column('copied_item_id', sa.Integer(), nullable=False),
        sa.Column('copied_by_company_id', sa.Integer(), nullable=False),
        sa.Column('copied_by_user_id', sa.Integer(), nullable=True),
        sa.Column('copied_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['original_item_id'], ['content_items.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['original_company_id'], ['companies.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['copied_item_id'], ['content_items.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['copied_by_company_id'], ['companies.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['copied_by_user_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_content_copies_id'), 'content_copies', ['id'], unique=False)

    # 8. Create content_api_tokens table (public API access)
    op.create_table(
        'content_api_tokens',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('company_id', sa.Integer(), nullable=False),
        sa.Column('knowledge_base_id', sa.Integer(), nullable=True),
        sa.Column('token', sa.String(64), nullable=False),
        sa.Column('name', sa.String(100), nullable=True),
        sa.Column('can_read', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('can_search', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('rate_limit', sa.Integer(), nullable=False, server_default='100'),
        sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('request_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['knowledge_base_id'], ['knowledge_bases.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('token', name='uq_content_api_tokens_token')
    )
    op.create_index(op.f('ix_content_api_tokens_id'), 'content_api_tokens', ['id'], unique=False)
    op.create_index(op.f('ix_content_api_tokens_token'), 'content_api_tokens', ['token'], unique=True)

    # 9. Create content_exports table
    op.create_table(
        'content_exports',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('company_id', sa.Integer(), nullable=False),
        sa.Column('knowledge_base_id', sa.Integer(), nullable=True),
        sa.Column('format', sa.String(20), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, server_default='pending'),
        sa.Column('s3_key', sa.String(500), nullable=True),
        sa.Column('file_size', sa.Integer(), nullable=True),
        sa.Column('item_count', sa.Integer(), nullable=True),
        sa.Column('filter_criteria', sa.String(500), nullable=True),
        sa.Column('requested_by', sa.Integer(), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['knowledge_base_id'], ['knowledge_bases.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['requested_by'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_content_exports_id'), 'content_exports', ['id'], unique=False)


def downgrade() -> None:
    """Drop CMS tables in reverse order."""
    op.drop_index(op.f('ix_content_exports_id'), table_name='content_exports')
    op.drop_table('content_exports')

    op.drop_index(op.f('ix_content_api_tokens_token'), table_name='content_api_tokens')
    op.drop_index(op.f('ix_content_api_tokens_id'), table_name='content_api_tokens')
    op.drop_table('content_api_tokens')

    op.drop_index(op.f('ix_content_copies_id'), table_name='content_copies')
    op.drop_table('content_copies')

    op.drop_index(op.f('ix_content_tags_slug'), table_name='content_tags')
    op.drop_index(op.f('ix_content_tags_id'), table_name='content_tags')
    op.drop_table('content_tags')

    op.drop_table('content_item_categories')

    op.drop_index(op.f('ix_content_categories_slug'), table_name='content_categories')
    op.drop_index(op.f('ix_content_categories_id'), table_name='content_categories')
    op.drop_table('content_categories')

    op.drop_index(op.f('ix_content_media_media_type'), table_name='content_media')
    op.drop_index(op.f('ix_content_media_id'), table_name='content_media')
    op.drop_table('content_media')

    op.drop_index('ix_content_items_data', table_name='content_items')
    op.drop_index(op.f('ix_content_items_visibility'), table_name='content_items')
    op.drop_index(op.f('ix_content_items_status'), table_name='content_items')
    op.drop_index(op.f('ix_content_items_id'), table_name='content_items')
    op.drop_table('content_items')

    op.drop_index(op.f('ix_content_types_slug'), table_name='content_types')
    op.drop_index(op.f('ix_content_types_id'), table_name='content_types')
    op.drop_table('content_types')

"""add deal_id and account_id to entity_notes

Revision ID: x3y4z5a6b7c8
Revises: w2x3y4z5a6b7
Create Date: 2026-05-01

"""
from alembic import op
import sqlalchemy as sa

revision = 'x3y4z5a6b7c8'
down_revision = 'w2x3y4z5a6b7'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('entity_notes', sa.Column('deal_id', sa.Integer(), nullable=True))
    op.add_column('entity_notes', sa.Column('account_id', sa.Integer(), nullable=True))
    op.create_foreign_key('fk_entity_notes_deal_id', 'entity_notes', 'deals', ['deal_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_entity_notes_account_id', 'entity_notes', 'accounts', ['account_id'], ['id'], ondelete='CASCADE')
    op.create_index('ix_entity_notes_deal_id', 'entity_notes', ['deal_id'])
    op.create_index('ix_entity_notes_account_id', 'entity_notes', ['account_id'])


def downgrade():
    op.drop_index('ix_entity_notes_account_id', table_name='entity_notes')
    op.drop_index('ix_entity_notes_deal_id', table_name='entity_notes')
    op.drop_constraint('fk_entity_notes_account_id', 'entity_notes', type_='foreignkey')
    op.drop_constraint('fk_entity_notes_deal_id', 'entity_notes', type_='foreignkey')
    op.drop_column('entity_notes', 'account_id')
    op.drop_column('entity_notes', 'deal_id')

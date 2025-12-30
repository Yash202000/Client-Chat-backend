"""add_freeswitch_phone_numbers

Revision ID: c9d0e1f2g3h4
Revises: b8c9d0e1f2g3
Create Date: 2025-12-30 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c9d0e1f2g3h4'
down_revision: Union[str, Sequence[str], None] = 'b8c9d0e1f2g3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create freeswitch_phone_numbers table."""
    op.create_table(
        'freeswitch_phone_numbers',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('phone_number', sa.String(), nullable=False),
        sa.Column('friendly_name', sa.String(), nullable=True),
        sa.Column('company_id', sa.Integer(), nullable=False),
        sa.Column('default_agent_id', sa.Integer(), nullable=True),
        sa.Column('is_active', sa.Boolean(), default=True),
        sa.Column('welcome_message', sa.String(), nullable=True),
        sa.Column('language', sa.String(), default='en-US'),
        sa.Column('audio_format', sa.String(), default='l16'),
        sa.Column('sample_rate', sa.Integer(), default=8000),
        sa.Column('freeswitch_server', sa.String(), nullable=True),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ),
        sa.ForeignKeyConstraint(['default_agent_id'], ['agents.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_freeswitch_phone_numbers_id'), 'freeswitch_phone_numbers', ['id'], unique=False)
    op.create_index(op.f('ix_freeswitch_phone_numbers_phone_number'), 'freeswitch_phone_numbers', ['phone_number'], unique=True)


def downgrade() -> None:
    """Drop freeswitch_phone_numbers table."""
    op.drop_index(op.f('ix_freeswitch_phone_numbers_phone_number'), table_name='freeswitch_phone_numbers')
    op.drop_index(op.f('ix_freeswitch_phone_numbers_id'), table_name='freeswitch_phone_numbers')
    op.drop_table('freeswitch_phone_numbers')

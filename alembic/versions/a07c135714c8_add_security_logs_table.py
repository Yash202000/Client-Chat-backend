"""add security_logs table

Revision ID: a07c135714c8
Revises: c9d0e1f2g3h4
Create Date: 2026-01-08 00:30:07.458948

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'a07c135714c8'
down_revision: Union[str, Sequence[str], None] = 'c9d0e1f2g3h4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Create security_logs table
    op.create_table(
        'security_logs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('event_type', sa.String(length=50), nullable=False),
        sa.Column('threat_level', sa.String(length=20), nullable=False),
        sa.Column('company_id', sa.Integer(), nullable=True),
        sa.Column('session_id', sa.String(length=255), nullable=True),
        sa.Column('user_ip', sa.String(length=45), nullable=True),
        sa.Column('blocked', sa.Integer(), nullable=True, default=1),
        sa.Column('original_message', sa.Text(), nullable=True),
        sa.Column('detected_patterns', sa.JSON(), nullable=True),
        sa.Column('sanitized_message', sa.Text(), nullable=True),
        sa.Column('channel', sa.String(length=50), nullable=True),
        sa.Column('user_agent', sa.String(length=500), nullable=True),
        sa.Column('additional_data', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ),
        sa.PrimaryKeyConstraint('id')
    )

    # Create indexes
    op.create_index(op.f('ix_security_logs_id'), 'security_logs', ['id'], unique=False)
    op.create_index(op.f('ix_security_logs_event_type'), 'security_logs', ['event_type'], unique=False)
    op.create_index(op.f('ix_security_logs_threat_level'), 'security_logs', ['threat_level'], unique=False)
    op.create_index(op.f('ix_security_logs_company_id'), 'security_logs', ['company_id'], unique=False)
    op.create_index(op.f('ix_security_logs_session_id'), 'security_logs', ['session_id'], unique=False)
    op.create_index(op.f('ix_security_logs_created_at'), 'security_logs', ['created_at'], unique=False)
    op.create_index('ix_security_logs_company_created', 'security_logs', ['company_id', 'created_at'], unique=False)
    op.create_index('ix_security_logs_event_threat', 'security_logs', ['event_type', 'threat_level'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    # Drop indexes
    op.drop_index('ix_security_logs_event_threat', table_name='security_logs')
    op.drop_index('ix_security_logs_company_created', table_name='security_logs')
    op.drop_index(op.f('ix_security_logs_created_at'), table_name='security_logs')
    op.drop_index(op.f('ix_security_logs_session_id'), table_name='security_logs')
    op.drop_index(op.f('ix_security_logs_company_id'), table_name='security_logs')
    op.drop_index(op.f('ix_security_logs_threat_level'), table_name='security_logs')
    op.drop_index(op.f('ix_security_logs_event_type'), table_name='security_logs')
    op.drop_index(op.f('ix_security_logs_id'), table_name='security_logs')

    # Drop table
    op.drop_table('security_logs')

"""company_onboarding — team_size, primary_use_case, onboarding_completed on companies

Revision ID: q2r3s4t5u6v7
Revises: p1q2r3s4t5u6
Create Date: 2026-06-08
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine.reflection import Inspector

revision = 'q2r3s4t5u6v7'
down_revision = 'p1q2r3s4t5u6'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = Inspector.from_engine(bind)

    company_cols = {c['name'] for c in inspector.get_columns('companies')}
    if 'team_size' not in company_cols:
        op.add_column('companies', sa.Column('team_size', sa.String(), nullable=True))
    if 'primary_use_case' not in company_cols:
        op.add_column('companies', sa.Column('primary_use_case', sa.String(), nullable=True))
    if 'onboarding_completed' not in company_cols:
        op.add_column('companies', sa.Column(
            'onboarding_completed', sa.Boolean(), nullable=False, server_default='false'))


def downgrade():
    op.drop_column('companies', 'onboarding_completed')
    op.drop_column('companies', 'primary_use_case')
    op.drop_column('companies', 'team_size')

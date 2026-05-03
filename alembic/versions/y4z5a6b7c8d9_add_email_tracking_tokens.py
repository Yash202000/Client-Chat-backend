"""add email_tracking_tokens table

Revision ID: y4z5a6b7c8d9
Revises: x3y4z5a6b7c8
Create Date: 2026-05-01

"""
from alembic import op
import sqlalchemy as sa

revision = 'y4z5a6b7c8d9'
down_revision = 'x3y4z5a6b7c8'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'email_tracking_tokens',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('company_id', sa.Integer(), nullable=False),
        sa.Column('token', sa.String(36), nullable=False),
        sa.Column('token_type', sa.Enum('open', 'click', name='trackingtokentype'), nullable=False),
        sa.Column('contact_id', sa.Integer(), nullable=True),
        sa.Column('deal_id', sa.Integer(), nullable=True),
        sa.Column('campaign_id', sa.Integer(), nullable=True),
        sa.Column('campaign_message_id', sa.Integer(), nullable=True),
        sa.Column('original_url', sa.Text(), nullable=True),
        sa.Column('email_subject', sa.String(), nullable=True),
        sa.Column('sent_by', sa.Integer(), nullable=True),
        sa.Column('first_fired_at', sa.DateTime(), nullable=True),
        sa.Column('last_fired_at', sa.DateTime(), nullable=True),
        sa.Column('fire_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('last_ip', sa.String(), nullable=True),
        sa.Column('last_user_agent', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['contact_id'], ['contacts.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['deal_id'], ['deals.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['campaign_id'], ['campaigns.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['campaign_message_id'], ['campaign_messages.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['sent_by'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('token'),
    )
    op.create_index('ix_email_tracking_tokens_id', 'email_tracking_tokens', ['id'])
    op.create_index('ix_email_tracking_tokens_token', 'email_tracking_tokens', ['token'])
    op.create_index('ix_email_tracking_tokens_company_id', 'email_tracking_tokens', ['company_id'])
    op.create_index('ix_email_tracking_tokens_contact_id', 'email_tracking_tokens', ['contact_id'])
    op.create_index('ix_email_tracking_tokens_deal_id', 'email_tracking_tokens', ['deal_id'])
    op.create_index('ix_email_tracking_tokens_token_type', 'email_tracking_tokens', ['token_type'])


def downgrade():
    op.drop_table('email_tracking_tokens')
    op.execute("DROP TYPE IF EXISTS trackingtokentype")

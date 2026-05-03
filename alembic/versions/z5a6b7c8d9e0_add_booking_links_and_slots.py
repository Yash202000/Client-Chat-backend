"""add booking_links and booking_slots tables

Revision ID: z5a6b7c8d9e0
Revises: y4z5a6b7c8d9
Create Date: 2026-05-01

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'z5a6b7c8d9e0'
down_revision = 'y4z5a6b7c8d9'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'booking_links',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('company_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('slug', sa.String(100), nullable=False),
        sa.Column('title', sa.String(255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('location', sa.String(500), nullable=True),
        sa.Column('duration_minutes', sa.Integer(), nullable=False, server_default='30'),
        sa.Column('buffer_before_minutes', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('buffer_after_minutes', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('availability', postgresql.JSONB(), nullable=False, server_default='{}'),
        sa.Column('timezone', sa.String(64), nullable=False, server_default='UTC'),
        sa.Column('max_advance_days', sa.Integer(), nullable=False, server_default='60'),
        sa.Column('min_notice_hours', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('color', sa.String(7), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('slug'),
    )
    op.create_index('ix_booking_links_id', 'booking_links', ['id'])
    op.create_index('ix_booking_links_slug', 'booking_links', ['slug'])
    op.create_index('ix_booking_links_company_id', 'booking_links', ['company_id'])
    op.create_index('ix_booking_links_user_id', 'booking_links', ['user_id'])

    op.create_table(
        'booking_slots',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('booking_link_id', sa.Integer(), nullable=False),
        sa.Column('calendar_event_id', sa.Integer(), nullable=True),
        sa.Column('booker_name', sa.String(255), nullable=False),
        sa.Column('booker_email', sa.String(255), nullable=False),
        sa.Column('booker_phone', sa.String(50), nullable=True),
        sa.Column('booker_notes', sa.Text(), nullable=True),
        sa.Column('start_time', sa.DateTime(), nullable=False),
        sa.Column('end_time', sa.DateTime(), nullable=False),
        sa.Column('status', sa.Enum('pending', 'confirmed', 'cancelled', name='bookingslotstatus'), nullable=False, server_default='confirmed'),
        sa.Column('contact_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['booking_link_id'], ['booking_links.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['calendar_event_id'], ['calendar_events.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['contact_id'], ['contacts.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_booking_slots_id', 'booking_slots', ['id'])
    op.create_index('ix_booking_slots_booking_link_id', 'booking_slots', ['booking_link_id'])
    op.create_index('ix_booking_slots_booker_email', 'booking_slots', ['booker_email'])
    op.create_index('ix_booking_slots_start_time', 'booking_slots', ['start_time'])
    op.create_index('ix_booking_slots_contact_id', 'booking_slots', ['contact_id'])


def downgrade():
    op.drop_table('booking_slots')
    op.execute("DROP TYPE IF EXISTS bookingslotstatus")
    op.drop_table('booking_links')

"""add email channel and subject to broadcasts

Revision ID: k6l7m8n9o0p1
Revises: j5k6l7m8n9o0
Create Date: 2026-05-23
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = 'k6l7m8n9o0p1'
down_revision = 'j5k6l7m8n9o0'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()

    # ── Enums ──────────────────────────────────────────────────────────────────
    # Use a PL/pgSQL exception handler so CREATE is atomic — avoids races with
    # create_all() that may have already created the type on app startup.
    for type_name, values in [
        ('broadcastchannel',       ['whatsapp', 'sms', 'email']),
        ('broadcaststatus',        ['draft', 'running', 'completed', 'failed', 'scheduled']),
        ('broadcastcontactstatus', ['pending', 'sent', 'failed', 'skipped']),
    ]:
        vals = ', '.join(f"'{v}'" for v in values)
        op.execute(sa.text(f"""
            DO $$ BEGIN
                CREATE TYPE {type_name} AS ENUM ({vals});
            EXCEPTION WHEN duplicate_object THEN NULL;
            END $$;
        """))
        # Always attempt to add each value — safe no-op if already present
        for v in values:
            op.execute(sa.text(f"ALTER TYPE {type_name} ADD VALUE IF NOT EXISTS '{v}'"))

    # ── broadcasts table ───────────────────────────────────────────────────────
    table_exists = conn.execute(
        sa.text("SELECT 1 FROM information_schema.tables WHERE table_name = 'broadcasts'")
    ).fetchone()

    if table_exists is None:
        op.create_table(
            'broadcasts',
            sa.Column('id', sa.Integer(), primary_key=True, index=True),
            sa.Column('company_id', sa.Integer(), sa.ForeignKey('companies.id'), nullable=False, index=True),
            sa.Column('name', sa.String(255), nullable=False),
            sa.Column('channel', sa.Enum('whatsapp', 'sms', 'email', name='broadcastchannel'), nullable=False),
            sa.Column('subject', sa.String(500), nullable=True),
            sa.Column('message', sa.Text(), nullable=False),
            sa.Column('segment_id', sa.Integer(), sa.ForeignKey('segments.id'), nullable=True),
            sa.Column('total_contacts', sa.Integer(), default=0),
            sa.Column('sent_count', sa.Integer(), default=0),
            sa.Column('failed_count', sa.Integer(), default=0),
            sa.Column('skipped_count', sa.Integer(), default=0),
            sa.Column('status', sa.Enum('draft', 'running', 'completed', 'failed', 'scheduled', name='broadcaststatus'), nullable=False),
            sa.Column('scheduled_at', sa.DateTime(), nullable=True),
            sa.Column('started_at', sa.DateTime(), nullable=True),
            sa.Column('completed_at', sa.DateTime(), nullable=True),
            sa.Column('created_by_user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False),
        )
    else:
        cols = [r[0] for r in conn.execute(
            sa.text("SELECT column_name FROM information_schema.columns WHERE table_name = 'broadcasts'")
        ).fetchall()]
        if 'subject' not in cols:
            op.add_column('broadcasts', sa.Column('subject', sa.String(500), nullable=True))

    # ── broadcast_contacts table ───────────────────────────────────────────────
    bc_exists = conn.execute(
        sa.text("SELECT 1 FROM information_schema.tables WHERE table_name = 'broadcast_contacts'")
    ).fetchone()

    if bc_exists is None:
        op.create_table(
            'broadcast_contacts',
            sa.Column('id', sa.Integer(), primary_key=True, index=True),
            sa.Column('broadcast_id', sa.Integer(), sa.ForeignKey('broadcasts.id', ondelete='CASCADE'), nullable=False, index=True),
            sa.Column('contact_id', sa.Integer(), sa.ForeignKey('contacts.id'), nullable=False),
            sa.Column('company_id', sa.Integer(), sa.ForeignKey('companies.id'), nullable=False),
            sa.Column('status', sa.Enum('pending', 'sent', 'failed', 'skipped', name='broadcastcontactstatus'), nullable=False),
            sa.Column('error_message', sa.Text(), nullable=True),
            sa.Column('sent_at', sa.DateTime(), nullable=True),
        )


def downgrade():
    op.drop_column('broadcasts', 'subject')
    # Note: PostgreSQL does not support removing enum values; downgrade leaves the enum intact

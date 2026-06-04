"""add email channel and subject to broadcasts

Revision ID: k6l7m8n9o0p1
Revises: j5k6l7m8n9o0
Create Date: 2026-05-23
"""
from alembic import op
import sqlalchemy as sa

revision = 'k6l7m8n9o0p1'
down_revision = 'j5k6l7m8n9o0'
branch_labels = None
depends_on = None


def upgrade():
    # ── Enum types ────────────────────────────────────────────────────────────
    # PL/pgSQL exception handler is atomic — safe whether create_all() already
    # created the type or not.
    # SQLAlchemy stores enum NAMES (uppercase) in Postgres by default, not values.
    op.execute(sa.text("""
        DO $$ BEGIN
            CREATE TYPE broadcastchannel AS ENUM ('WHATSAPP', 'SMS', 'EMAIL');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
    """))
    op.execute(sa.text("ALTER TYPE broadcastchannel ADD VALUE IF NOT EXISTS 'EMAIL'"))

    op.execute(sa.text("""
        DO $$ BEGIN
            CREATE TYPE broadcaststatus AS ENUM ('DRAFT', 'RUNNING', 'COMPLETED', 'FAILED', 'SCHEDULED');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
    """))
    op.execute(sa.text("ALTER TYPE broadcaststatus ADD VALUE IF NOT EXISTS 'SCHEDULED'"))

    op.execute(sa.text("""
        DO $$ BEGIN
            CREATE TYPE broadcastcontactstatus AS ENUM ('PENDING', 'SENT', 'FAILED', 'SKIPPED');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
    """))

    # ── broadcasts table ──────────────────────────────────────────────────────
    # Raw SQL bypasses SQLAlchemy's automatic CREATE TYPE on op.create_table.
    op.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS broadcasts (
            id          SERIAL PRIMARY KEY,
            company_id  INTEGER NOT NULL REFERENCES companies(id),
            name        VARCHAR(255) NOT NULL,
            channel     broadcastchannel NOT NULL,
            subject     VARCHAR(500),
            message     TEXT NOT NULL,
            segment_id  INTEGER REFERENCES segments(id),
            total_contacts  INTEGER DEFAULT 0,
            sent_count      INTEGER DEFAULT 0,
            failed_count    INTEGER DEFAULT 0,
            skipped_count   INTEGER DEFAULT 0,
            status          broadcaststatus NOT NULL DEFAULT 'DRAFT',
            scheduled_at    TIMESTAMP,
            started_at      TIMESTAMP,
            completed_at    TIMESTAMP,
            created_by_user_id INTEGER REFERENCES users(id),
            created_at  TIMESTAMP NOT NULL DEFAULT now()
        )
    """))

    # Add subject column in case the table already existed without it
    op.execute(sa.text("""
        DO $$ BEGIN
            ALTER TABLE broadcasts ADD COLUMN subject VARCHAR(500);
        EXCEPTION WHEN duplicate_column THEN NULL;
        END $$;
    """))

    # ── broadcast_contacts table ──────────────────────────────────────────────
    op.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS broadcast_contacts (
            id           SERIAL PRIMARY KEY,
            broadcast_id INTEGER NOT NULL REFERENCES broadcasts(id) ON DELETE CASCADE,
            contact_id   INTEGER NOT NULL REFERENCES contacts(id),
            company_id   INTEGER NOT NULL REFERENCES companies(id),
            status       broadcastcontactstatus NOT NULL,
            error_message TEXT,
            sent_at      TIMESTAMP
        )
    """))


def downgrade():
    op.execute(sa.text("DROP TABLE IF EXISTS broadcast_contacts"))
    op.execute(sa.text("DROP TABLE IF EXISTS broadcasts"))

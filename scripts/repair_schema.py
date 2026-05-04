"""
Repairs schema for databases set up without alembic tracking (e.g. via create_all()).
Creates missing tables and adds missing columns using IF NOT EXISTS — safe to run multiple times.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import create_engine, text, inspect
from app.core.database import Base
import app.models  # noqa: F401 — ensures all models are registered on Base.metadata

DATABASE_URL = os.environ["DATABASE_URL"]
engine = create_engine(DATABASE_URL)

# ---------------------------------------------------------------------------
# Step 1: create any tables that exist in models but not in the DB
# ---------------------------------------------------------------------------
print("Creating missing tables...")
Base.metadata.create_all(engine, checkfirst=True)
print("Done.")

# ---------------------------------------------------------------------------
# Step 2: add columns that were added by migrations after initial create_all
# Columns that exist in models but may be absent in older DB snapshots.
# ---------------------------------------------------------------------------
COLUMN_REPAIRS = [
    # users — chat features (o4p5q6r7s8t9)
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS status_message VARCHAR(255)",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS dnd_until TIMESTAMP WITH TIME ZONE",
    # users — voice features (l1m2n3o4p5q6)
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS skills JSON",
    # contacts (j9k0l1m2n3o4)
    "ALTER TABLE contacts ADD COLUMN IF NOT EXISTS profile_picture_url VARCHAR(500)",
    # contacts (v1w2x3y4z5a6)
    "ALTER TABLE contacts ADD COLUMN IF NOT EXISTS account_id INTEGER REFERENCES accounts(id) ON DELETE SET NULL",
    # internal_chat_messages (o4p5q6r7s8t9)
    "ALTER TABLE internal_chat_messages ADD COLUMN IF NOT EXISTS scheduled_at TIMESTAMP WITH TIME ZONE",
    # calendar_events (n3o4p5q6r7s8 + q6r7s8t9u0v1)
    "ALTER TABLE calendar_events ADD COLUMN IF NOT EXISTS location VARCHAR(500)",
    "ALTER TABLE calendar_events ADD COLUMN IF NOT EXISTS is_all_day BOOLEAN DEFAULT FALSE",
    # calendar_events — recurrence (p5q6r7s8t9u0)
    "ALTER TABLE calendar_events ADD COLUMN IF NOT EXISTS livekit_room_name VARCHAR(255)",
    "ALTER TABLE calendar_events ADD COLUMN IF NOT EXISTS recurrence_rule VARCHAR(20)",
    "ALTER TABLE calendar_events ADD COLUMN IF NOT EXISTS recurrence_interval INTEGER",
    "ALTER TABLE calendar_events ADD COLUMN IF NOT EXISTS recurrence_end_date DATE",
    "ALTER TABLE calendar_events ADD COLUMN IF NOT EXISTS parent_event_id INTEGER REFERENCES calendar_events(id) ON DELETE CASCADE",
    # calendar_events — video (u0v1w2x3y4z5)
    "ALTER TABLE calendar_events ADD COLUMN IF NOT EXISTS video_enabled BOOLEAN DEFAULT FALSE",
    # voice_calls (k0l1m2n3o4p5)
    "ALTER TABLE voice_calls ADD COLUMN IF NOT EXISTS recording_url VARCHAR(500)",
    "ALTER TABLE voice_calls ADD COLUMN IF NOT EXISTS recording_duration_secs INTEGER",
    # voice_calls (l1m2n3o4p5q6)
    "ALTER TABLE voice_calls ADD COLUMN IF NOT EXISTS csat_score INTEGER",
    "ALTER TABLE voice_calls ADD COLUMN IF NOT EXISTS csat_sent_at TIMESTAMP WITH TIME ZONE",
    # call_queue_entries (l1m2n3o4p5q6)
    "ALTER TABLE call_queue_entries ADD COLUMN IF NOT EXISTS required_skill VARCHAR(100)",
    "ALTER TABLE call_queue_entries ADD COLUMN IF NOT EXISTS voicemail_url VARCHAR(500)",
    "ALTER TABLE call_queue_entries ADD COLUMN IF NOT EXISTS overflow_at TIMESTAMP WITH TIME ZONE",
    # workflows (f5g6h7i8j9k0)
    "ALTER TABLE workflows ADD COLUMN IF NOT EXISTS agent_id INTEGER REFERENCES agents(id) ON DELETE SET NULL",
    # templates (a6b7c8d9e0f1)
    "ALTER TABLE templates ADD COLUMN IF NOT EXISTS design JSON",
    # entity_notes (x3y4z5a6b7c8)
    "ALTER TABLE entity_notes ADD COLUMN IF NOT EXISTS deal_id INTEGER REFERENCES deals(id) ON DELETE CASCADE",
    "ALTER TABLE entity_notes ADD COLUMN IF NOT EXISTS account_id INTEGER REFERENCES accounts(id) ON DELETE CASCADE",
]

print("Adding missing columns...")
with engine.begin() as conn:
    for stmt in COLUMN_REPAIRS:
        try:
            conn.execute(text(stmt))
            col = stmt.split("ADD COLUMN IF NOT EXISTS ")[1].split(" ")[0] if "ADD COLUMN" in stmt else stmt
            print(f"  OK: {col}")
        except Exception as e:
            print(f"  SKIP ({e})")

print("Schema repair complete.")

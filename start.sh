#!/bin/bash
set -e

echo "Checking database state..."

# Detect whether alembic_version exists and has a tracked version
DB_STATE=$(python - <<'PYEOF'
import os, sys
sys.path.insert(0, "/app")
from dotenv import load_dotenv
load_dotenv()
from sqlalchemy import create_engine, text
try:
    engine = create_engine(os.environ["DATABASE_URL"])
    with engine.connect() as conn:
        version = conn.execute(text("SELECT version_num FROM alembic_version LIMIT 1")).fetchone()
        if version:
            print("tracked")
        else:
            # Check if tables already exist (DB created without alembic)
            count = conn.execute(text(
                "SELECT COUNT(*) FROM information_schema.tables "
                "WHERE table_schema='public' AND table_name='users'"
            )).scalar()
            print("existing" if count > 0 else "fresh")
except Exception as e:
    print("fresh")
PYEOF
)

echo "Database state: $DB_STATE"

if [ "$DB_STATE" = "tracked" ]; then
    echo "Running incremental migrations..."
    alembic upgrade head
elif [ "$DB_STATE" = "existing" ]; then
    echo "Existing database without alembic tracking detected."
    echo "Stamping at head and repairing schema..."
    alembic stamp head
    python scripts/repair_schema.py
else
    echo "Fresh database. Running full migration..."
    alembic upgrade head
fi

echo "Starting application..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4

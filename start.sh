#!/bin/bash
set -e

echo "Running database migrations..."

alembic upgrade head > /tmp/alembic_out.txt 2>&1 && ALEMBIC_OK=true || ALEMBIC_OK=false
cat /tmp/alembic_out.txt

if [ "$ALEMBIC_OK" = "false" ]; then
    if grep -q "already exists\|DuplicateTable" /tmp/alembic_out.txt; then
        echo "Existing DB without alembic tracking detected. Stamping at head and repairing schema..."
        alembic stamp head
        python /app/scripts/repair_schema.py
    else
        echo "Migration failed with unexpected error. Exiting."
        exit 1
    fi
fi

echo "Starting application..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4

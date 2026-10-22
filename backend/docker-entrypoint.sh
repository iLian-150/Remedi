#!/bin/sh
set -eu

if [ "${SEED_DEMO_DATA:-true}" = "true" ]; then
    python seed.py
fi

exec uvicorn app.main:app --host 0.0.0.0 --port 8000

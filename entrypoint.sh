#!/bin/sh
set -e

echo "Running Alembic migrations..."
alembic upgrade head

echo "Starting tg-service-v2..."
exec python -m src.main

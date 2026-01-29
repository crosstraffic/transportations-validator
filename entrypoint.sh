#!/bin/bash
set -e

echo "Running migrations..."
alembic upgrade head

echo "Loading seed data..."
python -m scripts.load_seed_data

echo "Starting server..."
exec uvicorn transportations_validator.main:app --host 0.0.0.0 --port 8000 --reload

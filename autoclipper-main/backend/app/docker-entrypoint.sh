#!/usr/bin/env bash
# backend/docker-entrypoint.sh

# Start Celery worker in background
celery -A celery_app.celery worker --loglevel=info &

# Then start the FastAPI app
exec uvicorn app.main:app --host 0.0.0.0 --port 8000

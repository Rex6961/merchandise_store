#!/bin/sh
set -e

echo "Applying database migrations..."

python src/admin_panel/manage.py makemigrations clients

echo "Collecting static files..."
python src/admin_panel/manage.py collectstatic --noinput

python src/admin_panel/manage.py migrate

echo "Starting Gunicorn..."

exec python -m gunicorn src.admin_panel.merchandise_store.asgi:application \
    --bind 0.0.0.0:8000 \
    -w 1 \
    -k uvicorn.workers.UvicornWorker
#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

# Migrations/import run at startup: persistent disks are unavailable during builds.
# Both commands are repeatable. Existing saved route plans are preserved.
export RUNTIME_DIR="${RUNTIME_DIR:-.runtime}"
mkdir -p "$RUNTIME_DIR"
python manage.py migrate --noinput
python manage.py import_stations
exec python -m gunicorn config.wsgi:application --config gunicorn.conf.py

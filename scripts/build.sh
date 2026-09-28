#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

python -m pip install --disable-pip-version-check -r requirements.txt
python manage.py collectstatic --noinput

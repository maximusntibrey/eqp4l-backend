#!/usr/bin/env bash
# Container start: migrate, run the idempotent seed hook, then serve.
set -euo pipefail
cd "$(dirname "$0")/.."
# Production migrations need a verified backup first (TASKS 0.6), so auto-migrate is opt-in (local and CI only).
if [ "${AUTO_MIGRATE:-False}" = "True" ]; then
  python manage.py migrate --noinput
fi
bash scripts/seed.sh
if [ "${DJANGO_DEBUG:-False}" = "True" ]; then
  exec python manage.py runserver 0.0.0.0:8000
fi
exec gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers "${WEB_CONCURRENCY:-3}"

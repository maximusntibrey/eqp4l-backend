#!/usr/bin/env bash
# Container start: migrate, run the idempotent seed hook, then serve.
set -euo pipefail
cd "$(dirname "$0")/.."
# Auto-migrate is opt-in: set AUTO_MIGRATE=True on the host (Railway) and in local/CI.
if [ "${AUTO_MIGRATE:-False}" = "True" ]; then
  python manage.py migrate --noinput
fi
bash scripts/seed.sh
# Optional one-time bootstrap: set BOOTSTRAP_SUPERADMIN_NAME, read the one-time password from the logs, then remove the variable. The command refuses to run twice.
if [ -n "${BOOTSTRAP_SUPERADMIN_NAME:-}" ]; then
  python manage.py create_production_superadmin --full-name "$BOOTSTRAP_SUPERADMIN_NAME" || true
fi
if [ "${DJANGO_DEBUG:-False}" = "True" ]; then
  exec python manage.py runserver 0.0.0.0:8000
fi
exec gunicorn config.wsgi:application --bind 0.0.0.0:${PORT:-8000} --workers "${WEB_CONCURRENCY:-3}"

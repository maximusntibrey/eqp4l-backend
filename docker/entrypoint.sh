#!/bin/sh
# Container entrypoint (FIX-1). Waits for the database, applies migrations, collects static
# files if the build did not, optionally seeds local dev data, then runs the command.
# POSIX sh on purpose (python:slim has no bash guarantee). Must stay LF (.gitattributes).
#
#   DJANGO_MIGRATE_ON_START  1 runs `migrate --noinput`; default 0. Only compose.yaml (local)
#                            sets 1. Staging/production migrations stay a deploy step run
#                            after a verified backup (DevOps s4, s7), never on container start.
#   DJANGO_SEED_DEV          1 runs `manage.py seed_dev` IF that command exists.
#   DB_WAIT_SECONDS          how long to wait for the database (default 60).
set -eu

if [ "${1:-}" = "gunicorn" ] || [ "${DJANGO_ENTRYPOINT_FORCE:-0}" = "1" ]; then
  python - <<'PY'
import os, sys, time
import psycopg

url = os.environ["DATABASE_URL"]
deadline = time.monotonic() + int(os.environ.get("DB_WAIT_SECONDS", "60"))
while True:
    try:
        psycopg.connect(url, connect_timeout=3).close()
        break
    except psycopg.OperationalError as exc:
        if time.monotonic() > deadline:
            print("entrypoint: database not reachable, giving up:", type(exc).__name__, file=sys.stderr)
            sys.exit(1)
        print("entrypoint: waiting for the database...", flush=True)
        time.sleep(2)
PY

  if [ "${DJANGO_MIGRATE_ON_START:-0}" = "1" ]; then
    python manage.py migrate --noinput
  fi

  if [ ! -f staticfiles/staticfiles.json ]; then
    python manage.py collectstatic --noinput
  fi

  # TODO(B2.5): the seed_dev management command (SA/BA/WA/FS/Cashier logins, sample data)
  # arrives with B2.5. Until it exists this is a no-op; it is never faked here.
  if [ "${DJANGO_SEED_DEV:-0}" = "1" ]; then
    if python manage.py help seed_dev >/dev/null 2>&1; then
      python manage.py seed_dev
    else
      echo "entrypoint: DJANGO_SEED_DEV=1 but no seed_dev command yet (arrives with B2.5); skipping"
    fi
  fi
fi

exec "$@"

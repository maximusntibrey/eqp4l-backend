#!/usr/bin/env bash
# THE check command. Local: docker compose run --rm web bash scripts/check.sh   CI: same script.
# Needs DATABASE_URL pointing at a PostgreSQL server (compose "db" or the CI service).
set -euo pipefail
cd "$(dirname "$0")/.."

step() { printf '\n== %s\n' "$1"; }

step "ruff lint";            ruff check --quiet .
step "ruff format check";    ruff format --check --quiet .
step "mypy";                 mypy --no-error-summary .
step "bandit";               bandit -q -r . -c pyproject.toml
step "pip-audit";            pip-audit --disable-pip --require-hashes -r requirements.txt -r requirements-dev.txt --progress-spinner off
step "missing migrations";   DJANGO_DEBUG=True python manage.py makemigrations --check --dry-run
step "deploy sanity";        DJANGO_DEBUG=False DJANGO_SECRET_KEY="$(python -c 'import secrets;print(secrets.token_urlsafe(60))')" \
                             DJANGO_ALLOWED_HOSTS=example.invalid SECURE_HSTS_PRELOAD=True \
                             python manage.py check --deploy --fail-level WARNING
step "tests + coverage";     pytest
printf '\nCHECK OK\n'

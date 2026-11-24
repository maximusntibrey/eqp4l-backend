#!/usr/bin/env bash
# Idempotent dev seed hook (B2.5): SA-0001, one dev user per role, 3 branches + warehouse, sample items, prices, stock.
# Local only: skipped unless DJANGO_DEBUG=True (and manage.py seed_dev itself refuses when DEBUG is off).
set -euo pipefail
cd "$(dirname "$0")/.."
if [ "${DJANGO_DEBUG:-False}" = "True" ]; then
  python manage.py seed_dev
else
  echo "seed: DJANGO_DEBUG is not True, skipping dev seed"
fi

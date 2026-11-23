#!/usr/bin/env bash
# Local database backup with pg_dump (custom format). Usage: bash scripts/backup.sh [outfile]
# Runs against the compose "db" service. Production backups follow DevOps s7 and RUNBOOK.md.
set -euo pipefail
cd "$(dirname "$0")/.."
out="${1:-backups/eqp4l-$(date +%Y%m%d-%H%M%S).dump}"
mkdir -p "$(dirname "$out")"
docker compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -Fc "$POSTGRES_DB"' > "$out"
test -s "$out" || { echo "backup is empty: $out" >&2; exit 1; }
echo "backup written: $out"

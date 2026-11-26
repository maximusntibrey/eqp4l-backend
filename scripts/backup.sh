#!/usr/bin/env bash
# Local database and media volume backup. Usage: bash scripts/backup.sh [db_outfile] [media_outfile]
# Runs against the compose "db" service. Production backups follow DevOps s7 and RUNBOOK.md.
set -euo pipefail
cd "$(dirname "$0")/.."
stamp="$(date +%Y%m%d-%H%M%S)"
db_out="${1:-backups/eqp4l-${stamp}.dump}"
media_out="${2:-backups/eqp4l-media-${stamp}.tar.gz}"

mkdir -p "$(dirname "$db_out")"
docker compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -Fc "$POSTGRES_DB"' > "$db_out"
test -s "$db_out" || { echo "database backup is empty: $db_out" >&2; exit 1; }
echo "database backup written: $db_out"

# Media / image storage backup (O2.2)
mkdir -p "media"
if [ -z "$(ls -A media 2>/dev/null)" ]; then
  touch "media/.gitkeep"
fi
tar --force-local -czf "$media_out" -C . media
test -s "$media_out" || { echo "media backup is empty: $media_out" >&2; exit 1; }
echo "media backup written: $media_out"

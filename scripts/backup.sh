#!/usr/bin/env bash
# Database backup (T.14): pg_dump custom format (-Fc) to a timestamped file.
#
#   bash scripts/backup.sh [database]
#
# database   Database to dump (default: the container's POSTGRES_DB).
#
# Environment:
#   BACKUP_DIR              Output directory (default: ./backups, git-ignored)
#   BACKUP_RETENTION_DAYS   Optional. If set to a positive integer, dump files in BACKUP_DIR
#                           older than that many days are deleted after a successful backup.
#                           UNSET BY DEFAULT: nothing is ever deleted. The retention period is
#                           an open owner decision (OQ-3, GAP-M10); do not set one here until
#                           the owner confirms it.
#   COMPOSE_DB_SERVICE, PG_EXEC   see scripts/_pg.sh
#
# Prints the path of the dump on stdout. No secrets are used or stored by this script.
set -euo pipefail
# shellcheck source=scripts/_pg.sh
source "$(dirname "${BASH_SOURCE[0]}")/_pg.sh"

db="${1:-$(pg_default_db)}"
require_ident "$db"

out_dir="${BACKUP_DIR:-$REPO_ROOT/backups}"
mkdir -p "$out_dir"
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
out="$out_dir/${db}-${stamp}.dump"

# Write to a temp name first so a failed dump never leaves a file that looks valid.
if ! pg_exec sh -c 'exec pg_dump -Fc -U "$POSTGRES_USER" -d "$1"' sh "$db" >"$out.partial"; then
  rm -f "$out.partial"
  echo "error: pg_dump failed for database '$db'" >&2
  exit 1
fi
if [[ ! -s "$out.partial" ]]; then
  rm -f "$out.partial"
  echo "error: pg_dump produced an empty file for database '$db'" >&2
  exit 1
fi
mv "$out.partial" "$out"
echo "backup: wrote $out ($(wc -c <"$out") bytes)" >&2

if [[ -n "${BACKUP_RETENTION_DAYS:-}" ]]; then
  if [[ ! "$BACKUP_RETENTION_DAYS" =~ ^[1-9][0-9]*$ ]]; then
    echo "error: BACKUP_RETENTION_DAYS must be a positive integer" >&2
    exit 2
  fi
  find "$out_dir" -maxdepth 1 -name '*.dump' -type f -mtime "+$BACKUP_RETENTION_DAYS" -print -delete >&2
fi

echo "$out"

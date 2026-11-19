#!/usr/bin/env bash
# Restore a backup made by scripts/backup.sh into a target database (T.14).
#
#   bash scripts/restore.sh <dump-file> <target-database> [--force]
#
# The target database is created if it does not exist. If it exists and already contains
# tables, the restore is REFUSED unless --force is given (then existing objects are dropped
# and replaced). Restore into a new, empty database whenever possible (DevOps s7: "restore
# into a new database").
#
# Never point this at staging or production without the owner's go-ahead.
# Environment: COMPOSE_DB_SERVICE, PG_EXEC (see scripts/_pg.sh).
set -euo pipefail
# shellcheck source=scripts/_pg.sh
source "$(dirname "${BASH_SOURCE[0]}")/_pg.sh"

usage() {
  echo "usage: bash scripts/restore.sh <dump-file> <target-database> [--force]" >&2
  exit 2
}

[[ $# -ge 2 && $# -le 3 ]] || usage
dump="$1"
target="$2"
force="${3:-}"
[[ -z "$force" || "$force" == "--force" ]] || usage
require_ident "$target"
[[ -s "$dump" ]] || { echo "error: dump file '$dump' not found or empty" >&2; exit 2; }

exists="$(echo "SELECT 1 FROM pg_database WHERE datname = '$target'" | pg_psql postgres)"
if [[ "$exists" != "1" ]]; then
  echo "CREATE DATABASE \"$target\"" | pg_psql postgres
  echo "restore: created database '$target'" >&2
else
  tables="$(echo "SELECT count(*) FROM pg_tables WHERE schemaname NOT IN ('pg_catalog','information_schema')" | pg_psql "$target")"
  if [[ "$tables" != "0" && "$force" != "--force" ]]; then
    echo "error: database '$target' already has $tables table(s); refusing to overwrite. Use a new database name or pass --force." >&2
    exit 3
  fi
fi

args=(--no-owner --exit-on-error)
[[ "$force" == "--force" ]] && args+=(--clean --if-exists)

pg_exec sh -c 'd=$1; shift; exec pg_restore -U "$POSTGRES_USER" -d "$d" "$@"' sh "$target" "${args[@]}" <"$dump"
echo "restore: restored '$dump' into '$target'" >&2

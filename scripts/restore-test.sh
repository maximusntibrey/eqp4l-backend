#!/usr/bin/env bash
# Scripted restore test: restores a dump into a throwaway database and checks it is readable.
# Usage: bash scripts/restore-test.sh backups/<file>.dump   (never touches the real database)
set -euo pipefail
cd "$(dirname "$0")/.."
dump="${1:?usage: restore-test.sh <dump file>}"
test -s "$dump" || { echo "dump missing or empty: $dump" >&2; exit 1; }
scratch="restore_test_$$"
psql_db() { docker compose exec -T db sh -c "psql -v ON_ERROR_STOP=1 -U \"\$POSTGRES_USER\" -d postgres -tA -c \"$1\""; }
cleanup() { psql_db "DROP DATABASE IF EXISTS ${scratch}" >/dev/null; }
trap cleanup EXIT
psql_db "CREATE DATABASE ${scratch}" >/dev/null
docker compose exec -T db sh -c "pg_restore -U \"\$POSTGRES_USER\" -d ${scratch} --no-owner" < "$dump"
tables=$(docker compose exec -T db sh -c "psql -U \"\$POSTGRES_USER\" -d ${scratch} -tA -c \"SELECT count(*) FROM information_schema.tables WHERE table_schema='public'\"")
echo "restore ok: ${tables} public tables in scratch database ${scratch} (dropped afterwards)"
test "${tables}" -gt 0

#!/usr/bin/env bash
# Shared helpers for backup.sh, restore.sh and restore-test.sh (T.14). Source it; do not run it.
#
# pg_dump, pg_restore and psql are not installed on the Windows machine (SKILLS.md
# Appendix A), so they run inside the pinned PostgreSQL image through Docker Compose
# (service "db"). The client therefore always matches the server version. Credentials are
# read inside the container from its own environment (POSTGRES_USER), so no secret is in
# these scripts and none appears on the command line.
#
# Overrides (environment variables):
#   COMPOSE_DB_SERVICE  Compose service name of the database (default: db)
#   PG_EXEC             Full command prefix that runs a command inside the database
#                       container (default: docker compose exec -T <service>)

# Stop Git Bash on Windows from rewriting "/..." arguments.
export MSYS_NO_PATHCONV=1

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_DB_SERVICE="${COMPOSE_DB_SERVICE:-db}"

pg_exec() {
  if [[ -n "${PG_EXEC:-}" ]]; then
    # shellcheck disable=SC2086  # PG_EXEC is a command prefix, split on purpose
    (cd "$REPO_ROOT" && $PG_EXEC "$@")
  else
    (cd "$REPO_ROOT" && docker compose exec -T "$COMPOSE_DB_SERVICE" "$@")
  fi
}

# psql against a database, as the container's POSTGRES_USER. SQL is read from stdin.
# Usage: pg_psql <dbname> [extra psql args]   (adds -X -q -v ON_ERROR_STOP=1 -t -A)
pg_psql() {
  local db="$1"
  shift
  pg_exec sh -c 'd=$1; shift; exec psql -X -q -v ON_ERROR_STOP=1 -t -A -U "$POSTGRES_USER" -d "$d" "$@"' sh "$db" "$@"
}

# The default database name from the container's environment.
pg_default_db() {
  pg_exec sh -c 'printf %s "$POSTGRES_DB"'
}

# Database names are interpolated into SQL: allow only simple identifiers.
require_ident() {
  if [[ ! "$1" =~ ^[A-Za-z_][A-Za-z0-9_]{0,62}$ ]]; then
    echo "error: '$1' is not a simple database name (letters, digits, underscore)" >&2
    exit 2
  fi
}

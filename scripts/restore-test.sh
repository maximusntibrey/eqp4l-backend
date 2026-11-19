#!/usr/bin/env bash
# Scripted restore test (T.14): "a backup that has never been restored is not a verified
# backup" (DevOps s7).
#
#   bash scripts/restore-test.sh
#
# Creates two throwaway databases (eqp4l_rt_src_<id>, eqp4l_rt_dst_<id>) on the Compose
# database, loads sample data, backs it up with scripts/backup.sh, restores it with
# scripts/restore.sh into the fresh second database, and compares per-table row counts and
# md5 checksums of the full row contents. Also checks that restore.sh refuses to overwrite a
# non-empty database. The throwaway databases and the dump are removed at the end.
# It never touches the real application database.
#
# Exit code: 0 if everything matches; non-zero on any mismatch or error.
# Prints the elapsed time of the backup and the restore (recovery-time evidence).
# Environment: COMPOSE_DB_SERVICE, PG_EXEC (see scripts/_pg.sh).
set -euo pipefail
here="$(dirname "${BASH_SOURCE[0]}")"
# shellcheck source=scripts/_pg.sh
source "$here/_pg.sh"

id="$(date -u +%Y%m%d%H%M%S)_$$"
src="eqp4l_rt_src_$id"
dst="eqp4l_rt_dst_$id"
work="$(mktemp -d)"
dump=""

cleanup() {
  for d in "$src" "$dst"; do
    echo "DROP DATABASE IF EXISTS \"$d\" WITH (FORCE)" | pg_psql postgres >/dev/null 2>&1 || true
  done
  [[ -n "$dump" ]] && rm -f "$dump"
  rmdir "$work" 2>/dev/null || true
}
trap cleanup EXIT

echo "restore-test: creating source database $src with sample data"
echo "CREATE DATABASE \"$src\"" | pg_psql postgres
pg_psql "$src" <<'SQL'
CREATE TABLE branch (id serial PRIMARY KEY, name text NOT NULL UNIQUE);
CREATE TABLE item (
  id serial PRIMARY KEY,
  branch_id int NOT NULL REFERENCES branch (id),
  sku text NOT NULL,
  note text,
  price numeric(12, 2) NOT NULL,
  created_at timestamptz NOT NULL
);
INSERT INTO branch (name) VALUES ('Warehouse'), ('Branch A'), ('Branch B');
INSERT INTO item (branch_id, sku, note, price, created_at)
SELECT 1 + (g % 3), 'SKU-' || lpad(g::text, 5, '0'),
       CASE WHEN g % 7 = 0 THEN NULL ELSE 'note ' || g || ' é ü ₵' END,
       (g * 1.37)::numeric(12, 2), timestamptz '2026-01-01 00:00:00+00' + g * interval '1 hour'
FROM generate_series(1, 500) AS g;
SQL

fingerprint() { # <db>: one line per table, "name|rows|md5"
  pg_psql "$1" <<'SQL'
SELECT 'branch|' || count(*) || '|' || coalesce(md5(string_agg(b::text, ';' ORDER BY id)), '') FROM branch b;
SELECT 'item|' || count(*) || '|' || coalesce(md5(string_agg(i::text, ';' ORDER BY id)), '') FROM item i;
SQL
}

before="$(fingerprint "$src")"
echo "restore-test: source fingerprint:"
echo "$before" | sed 's/^/  /'

t0="$(date +%s)"
dump="$(BACKUP_DIR="$work" bash "$here/backup.sh" "$src")"
t1="$(date +%s)"
echo "restore-test: backup took $((t1 - t0))s"

echo "restore-test: restoring into fresh database $dst"
bash "$here/restore.sh" "$dump" "$dst"
t2="$(date +%s)"
echo "restore-test: restore took $((t2 - t1))s"

after="$(fingerprint "$dst")"
echo "restore-test: restored fingerprint:"
echo "$after" | sed 's/^/  /'

if [[ "$before" != "$after" ]]; then
  echo "restore-test: FAILED, row counts or checksums differ" >&2
  exit 1
fi

# The restore script must refuse to overwrite a non-empty database without --force.
rc=0
bash "$here/restore.sh" "$dump" "$dst" >/dev/null 2>&1 || rc=$?
if [[ "$rc" -ne 3 ]]; then
  echo "restore-test: FAILED, restore.sh exit code was $rc, expected 3 (refusal of a non-empty database without --force)" >&2
  exit 1
fi
echo "restore-test: restore.sh refused the non-empty target as expected"

echo "restore-test: PASSED (row counts and checksums match)"

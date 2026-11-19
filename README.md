# eqp4l-backend

Django REST API for the Payless4Laptops Inventory & Warehouse System. It owns every business rule, permission and stock change. The React frontend lives in the separate repository `p4linventory-frontend`; the OpenAPI contract published from this repo is the only link between the two.

## Project documents

| File | What it is |
|---|---|
| [TASKS.md](TASKS.md) | Enforced rules, git workflow and the step list. Steps for this repo are ticked here |
| [SKILLS.md](SKILLS.md) | Technical standards, AI agent rules, and this repo's install register (Appendix A) |
| [docs/project/](docs/project/README.md) | Copies of the project requirements: overview, frontend, backend, DevOps, gaps, and background documents |

Precedence: `1-Overview-and-Sprints`, `2-Frontend-Requirements`, `3-Backend-Requirements` and `4-DevOps-Requirements` win; `TASKS.md` and `SKILLS.md` follow them; documents 5 and 6 are background only. The originals were PDF files; only the Markdown conversions are kept in git (no binaries).

## Status

Sprint 1, tooling (B1.0). The stack is Python 3.13, Django 5.2 LTS, Django REST Framework and PostgreSQL (TASKS section 2.3). The Django project package is `eqp4l/`. There are no project apps, models or migrations yet: they wait for the owner's approval of the B1.2 ERD.

## Local setup

1. Set the git identity locally (TASKS 1.2).
2. Install the pre-commit hooks (lint and secret blocking, step T.3), see `SKILLS.md` Appendix A:

   ```
   pre-commit install --allow-missing-config
   pre-commit run --all-files
   ```

3. Create the virtual environment with Python 3.13 and install the pinned, hash-checked requirements (Git Bash on Windows shown; on Linux use `python3.13 -m venv .venv` and `.venv/bin/python`):

   ```
   py -V:3.13 -m venv .venv
   .venv/Scripts/python.exe -m pip install --require-hashes -r requirements/base.txt -r requirements/dev.txt
   ```

4. Copy `.env.example` to `.env` and fill in local values (at least a new `POSTGRES_PASSWORD`, letters and digits only, and the same value inside `DATABASE_URL`). `.env` is git-ignored. Never commit secrets.
5. Start the local stack with Docker (see "Local environment (Docker Compose)" below), or start only the database with `docker compose up -d db` and run Django from the venv.
6. Run the single check command (lint, format, type check, security scans, migration check, tests):

   ```
   bash scripts/check.sh
   ```

To change a dependency, edit `requirements/base.in` or `requirements/dev.in` and re-run `pip-compile --generate-hashes --allow-unsafe --strip-extras` on it (base first). One dependency per branch, recorded in `SKILLS.md` Appendix A.

## Local environment (Docker Compose, O1.2)

`compose.yaml` runs the Django app (gunicorn, non-root, built from `Dockerfile`) and PostgreSQL 18.7 (same image digest as CI). PostgreSQL is published on `127.0.0.1` only, data lives in the named volume `eqp4l_pgdata`, and all settings come from the git-ignored `.env`.

```
cp .env.example .env                # then edit the passwords
docker compose up -d --build        # builds the app image, waits for the database healthcheck
docker compose ps                   # db should be "healthy"
docker compose exec app python manage.py check --database default   # settings + database connection
docker compose down                 # stop (keeps the data); add -v to also delete the volume
```

The app answers on `http://127.0.0.1:8000/`. There is no `/health/` yet (O1.7). Use `127.0.0.1`, not `localhost`, on Windows. If port 5432 is taken, set `POSTGRES_PORT` in `.env` (and in `DATABASE_URL`).

## Backup and restore (T.14)

These scripts run `pg_dump`, `pg_restore` and `psql` inside the Compose `db` container (nothing needs installing on the host).

```
bash scripts/backup.sh [database]                      # writes backups/<db>-<UTC timestamp>.dump (git-ignored)
bash scripts/restore.sh <dump> <new-database>          # refuses a non-empty target unless --force is added
bash scripts/restore-test.sh                           # sample data -> backup -> restore into a fresh DB -> compare counts and checksums
```

`restore-test.sh` exits non-zero on any mismatch; it only uses throwaway databases and runs in CI. Retention is not decided (OQ-3 / GAP-M10): `BACKUP_RETENTION_DAYS` is unset by default, so nothing is ever deleted. Recovery procedure: `RUNBOOK.md` (O1.7/O2.x).

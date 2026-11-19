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

4. Copy `.env.example` to `.env` (`copy .env.example .env` in PowerShell, `cp` in Git Bash). If you change `POSTGRES_PASSWORD` (letters and digits only), change it inside `DATABASE_URL` too. `.env` is git-ignored. Never commit secrets.
5. Start the local stack with Docker (see "Local environment (Docker Compose)" below), or start only the database with `docker compose up -d db` and run Django from the venv.
6. Run the single check command (lint, format, type check, security scans, migration check, tests). It needs the venv from step 3 and the database from step 5; `make` is not used or needed:

   ```
   bash scripts/check.sh        # Git Bash on Windows, or bash on Linux
   ```

   No Git Bash? The same check inside Docker, against the Compose database (the `-v` mount keeps the dev tools out of the runtime image):

   ```
   docker compose up -d --wait db
   docker run --rm --network eqp4l_default -v "${PWD}:/src" -w /src -e DATABASE_URL=postgres://eqp4l:changeme@db:5432/eqp4l -e DJANGO_SECRET_KEY=local-check -e DJANGO_LOCAL=true python:3.13-slim bash -c "pip install -q --require-hashes -r requirements/base.txt -r requirements/dev.txt && bash scripts/check.sh"
   ```

To change a dependency, edit `requirements/base.in` or `requirements/dev.in` and re-run `pip-compile --generate-hashes --allow-unsafe --strip-extras` on it (base first). One dependency per branch, recorded in `SKILLS.md` Appendix A.

## Local environment (Docker Compose, O1.2)

`compose.yaml` runs the Django app (gunicorn, non-root, built from `Dockerfile`) and PostgreSQL 18.7 (same image digest as CI). PostgreSQL is published on `127.0.0.1` only, data lives in the named volume `eqp4l_pgdata`, and all settings come from the git-ignored `.env`.

```
docker compose up -d --build        # works from a fresh clone; .env is optional (see below)
docker compose ps                   # db should be "healthy"
docker compose exec app python manage.py check --database default   # settings + database connection
docker compose down                 # stop (keeps the data); add -v to also delete the volume
```

The app answers on `http://127.0.0.1:8000/health/` (200 `ok` when the app and database are up, 503 `unavailable` otherwise); `docker compose ps` shows the app as healthy. Use `127.0.0.1`, not `localhost`, on Windows. PostgreSQL is published on host port 5433 by default (so it does not clash with a Postgres installed on Windows); change `POSTGRES_PORT` and `APP_PORT` in `.env` (and the port in `DATABASE_URL`) if needed.

## Run it locally (Windows)

Prerequisites: Windows 10/11 with WSL2 enabled, Docker Desktop 4.30 or newer (WSL2 backend, status "Engine running"), Git for Windows 2.40 or newer, PowerShell 5.1 or newer. Python is not needed to run the app (only for `scripts/check.sh`: Python 3.13, `py -V:3.13`).

```powershell
git clone https://github.com/maximusntibrey/eqp4l-backend.git
cd eqp4l-backend
git checkout sprint/1-foundations
powershell -ExecutionPolicy Bypass -File scripts\dev.ps1
```

`scripts\dev.ps1` checks that Docker is running, creates `.env` from `.env.example` if it is missing, runs `docker compose up -d --build`, waits for `/health/` and prints the URLs. The manual equivalent is `copy .env.example .env` then `docker compose up -d --build` (the `.env` is optional: Compose has safe local defaults). On start the app container waits for the database, applies migrations (`migrate --noinput`) and, only if `DJANGO_SEED_DEV=1` and a `seed_dev` command exists, seeds dev data.

- Health: http://127.0.0.1:8000/health/ (200 `ok` when the app and database are up). Use `127.0.0.1`, not `localhost`, on Windows.
- API schema and docs: not served by the app. The contract is the file `openapi/openapi.yaml` (v0.2.0, B1.3); the `/api/v1/` endpoints are built from B2 on, so for now `/health/` is the only live route.
- PostgreSQL for tools: `127.0.0.1:5433` (user, password and database from `.env`).
- Dev logins: they arrive with B2.5 (`seed_dev`), together with the user model (B2.2) and login (B2.3). Their passwords will come from `DEV_SEED_PASSWORD_*` in your own git-ignored `.env`. There is no login to try before then.
- Frontend: run the Vite dev server on http://localhost:5173 with a proxy so the browser sees one origin (no CORS needed): `server: { proxy: { '/api': 'http://127.0.0.1:8000', '/health': 'http://127.0.0.1:8000' } }`. Django already trusts `http://localhost:5173` and `http://127.0.0.1:5173` for CSRF and allows non-HTTPS cookies in local mode (`DJANGO_LOCAL=true`); production refuses insecure cookies.
- Reset the local database (deletes all local data): `docker compose down -v`, then run `scripts\dev.ps1` again. Do this after pulling B2.2 (the custom user model): migrations applied before it cannot be switched to the new user table.
- Stop, keep the data: `docker compose down`. Logs: `docker compose logs -f app`.

Common errors:

| Symptom | Fix |
|---|---|
| `ports are not available ... 5433` (or 8000) | Something uses the port. Find it: `netstat -ano \| findstr :5433`, then change `POSTGRES_PORT` (or `APP_PORT`) in `.env` and the port in `DATABASE_URL`. |
| `error during connect ... docker_engine` / "Docker is not running" | Start Docker Desktop and wait for "Engine running", then retry. |
| "WSL 2 is not installed" / Docker Desktop will not start | In an admin PowerShell: `wsl --install`, reboot, and enable "Use WSL 2 based engine" in Docker Desktop settings. |
| `entrypoint.sh: not found` or `bad interpreter ^M` | CRLF line endings. `.gitattributes` forces LF; if a checkout predates it, run `git add --renormalize .` or re-clone. The image also strips CR from the entrypoint. |
| `/health/` times out on `localhost` | Use `http://127.0.0.1:8000/health/` (IPv6 `localhost` issue). |
| `required variable ... is missing` | Update to the latest branch: Compose no longer needs `.env`. |

## Backup and restore (T.14)

These scripts run `pg_dump`, `pg_restore` and `psql` inside the Compose `db` container (nothing needs installing on the host).

```
bash scripts/backup.sh [database]                      # writes backups/<db>-<UTC timestamp>.dump (git-ignored)
bash scripts/restore.sh <dump> <new-database>          # refuses a non-empty target unless --force is added
bash scripts/restore-test.sh                           # sample data -> backup -> restore into a fresh DB -> compare counts and checksums
```

`restore-test.sh` exits non-zero on any mismatch; it only uses throwaway databases and runs as a step of the CI `check` job. Retention is not decided (OQ-3 / GAP-M10): `BACKUP_RETENTION_DAYS` is unset by default, so nothing is ever deleted. Recovery procedure: `RUNBOOK.md` (O1.7/O2.x).

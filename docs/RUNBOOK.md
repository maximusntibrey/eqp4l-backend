# Host-Agnostic Runbook

## Environments

- Local: Docker Compose with debug enabled.
- Staging-equivalent: `docker compose -f docker-compose.yml -f docker-compose.staging.yml`.
- Production: Railway project `test-production`; backend `eqp4l-backend`, frontend `p4l-inventory`.

Railway uses the existing PostgreSQL service `Postgres` through `${{Postgres.DATABASE_URL}}`. Backend uploads use Django `FileSystemStorage` on a Railway Volume intended to be mounted at `/data` (`MEDIA_ROOT=/data/media`); no object-storage bucket is used. Public domains are `eqp4l-backend-production.up.railway.app` and `p4l-inventory-production.up.railway.app`. Confirm the actual volume mount in Railway before release.

The deployment target is `main` for both services (verified with the Railway CLI). Production variables belong in Railway's variable store, never in git. The backend `DJANGO_ALLOWED_HOSTS` must include `healthcheck.railway.app` and `PORT` must match the domain target port (8080). The frontend `VITE_API_URL` must be set before its build and changes require a redeploy.

## Production release gate

Take a verified database-and-volume backup before loading real data. Railway Trial cannot create backups; use `scripts/backup.sh` / `scripts/backup.ps1` against the hosted database until a Railway backup is available.

## Staging

```powershell
.\scripts\staging.ps1 up
.\scripts\staging.ps1 smoke
.\scripts\staging.ps1 down
```

The staging-equivalent configuration enables secure-cookie, redirect and HSTS settings. Set real hosts and Sentry DSN only through the secret store or environment variables.

## Backup

```powershell
.\scripts\backup.ps1
```

To register a local daily 02:00 backup:

```powershell
.\scripts\backup-schedule.ps1
```

Local archives are retained for the whole project. Configure the production database and volume retention only after the owner-approved backup method is available; verify a restore before production release.

## Restore

Restore is only to a throwaway database. Use `scripts/restore-test.sh` from Bash or the documented Docker commands in `scripts/restore-test.sh`.

## Rollback

1. Stop new writes and inform the owner.
2. Take a verified backup before rollback.
3. Restore the previous application image/tag.
4. Run migrations forward/back only after reviewing migration compatibility. `branches/0002` (drops the one-warehouse constraint) reverses only while at most one warehouse exists; otherwise it stops with an error and changes nothing.
5. Run `/health/`, login, dashboard, item list and Find smoke checks.
6. Record the result in `docs/DEPLOYMENT_LOG.md`.

## API smoke test

`scripts/api-smoke.py` (Python 3 standard library only) logs in over HTTP like the browser does (CSRF cookie, `Origin` header, `Idempotency-Key`), checks the CORS preflight, calls every GET endpoint, then runs safe write cycles: a draft item (create, edit), a user (create, edit, deactivate), a branch (create, edit, deactivate), a goods receipt, a dispatch received at a branch, a sale cancelled again and a CSV import dry run. Each call is printed with its status and a verdict. It exits 1 on any 5xx, missing CORS header, CSRF refusal or a write the role should be able to do. A 403 on an endpoint the role may not use prints `403 (role)` and is fine.

```
python scripts/api-smoke.py --login SA-0001 --password "<password>"
python scripts/api-smoke.py --base https://staging.example --origin https://frontend.example --login USR-0001 --password "<password>"
```

Options: `--base` (default `http://localhost:8000`), `--origin` (default `http://localhost:5173`), `--login`, `--password` (or `API_SMOKE_PASSWORD`). The writes are real rows: run it against a local or staging stack, never production. `tests/test_api_matrix.py` is the pytest twin: every operation in `openapi.yaml` for every role, the Idempotency-Key rules, the CORS preflight of every write path and every GET response checked against its published schema.

## Monitoring

Set `SENTRY_DSN` and `SENTRY_ENVIRONMENT` for a monitored environment. `/health/` must remain accessible and must check both application and database.

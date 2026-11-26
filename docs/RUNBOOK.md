# Host-Agnostic Runbook

## Environments

- Local: Docker Compose with debug enabled.
- Staging-equivalent: `docker compose -f docker-compose.yml -f docker-compose.staging.yml`.
- Production: Railway project `test-production`; backend `eqp4l-backend`, frontend `p4l-inventory`.

Railway uses the existing PostgreSQL service `Postgres` through `${{Postgres.DATABASE_URL}}`. Backend uploads use Django `FileSystemStorage` on a Railway Volume intended to be mounted at `/data` (`MEDIA_ROOT=/data/media`); no object-storage bucket is used. Public domains are `eqp4l-backend-production.up.railway.app` and `p4l-inventory-production.up.railway.app`. Confirm the actual volume mount in Railway before release.

The deployment target is `main` for both services. On 2026-11-26, both Railway production services were found connected to `sprint/2-mvp-release`; auto-deploy was disabled for both to prevent further sprint pushes from deploying. Set and verify the source branch as `main` only after the backup gate is satisfied. Production variables belong in Railway's variable store, never in git. The frontend `VITE_API_URL` must be set before its build and changes require a redeploy.

## Production release gate

The owner approved production work, but a verified database-and-volume backup is still unavailable. On 2026-11-26, sprint-branch pushes triggered an unintended partial Railway deployment: the frontend status succeeded and `/login` returned HTTP 200; the backend status failed and `/health/` returned HTTP 502. The backend deployment screen showed initialization, build, and deploy had not started, so there is no evidence that its `preDeployCommand` ran; confirm migration state from Railway and the database before any further deployment. Auto-deploy is disabled for both services. Do not merge to `main`, re-enable auto-deploy, or deploy until a backup has been created and restored successfully. An empty-looking database is not a waiver.

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
4. Run migrations forward/back only after reviewing migration compatibility.
5. Run `/health/`, login, dashboard, item list and Find smoke checks.
6. Record the result in `docs/DEPLOYMENT_LOG.md`.

## Monitoring

Set `SENTRY_DSN` and `SENTRY_ENVIRONMENT` for a monitored environment. `/health/` must remain accessible and must check both application and database.

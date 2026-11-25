# Host-Agnostic Runbook

## Environments

- Local: Docker Compose with debug enabled.
- Staging-equivalent: `docker compose -f docker-compose.yml -f docker-compose.staging.yml`.
- Production: only on the chosen host, after owner go-ahead.

No provider is selected by this repository. Hosting and domain values belong in the environment and secret store, never in git.

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

Use the release backup retention policy chosen with the hosting provider.

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

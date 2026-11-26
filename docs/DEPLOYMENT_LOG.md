# Deployment Log

Railway deploys from `main` for both services. A first deploy of `main` (initial commit only) failed; after `main` was restored (backend `9eadc29`, `71206b7`) the backend deployed and `/health/` returns `{"status":"ok","database":"ok"}`. No `v1.0.0` tag or release sign-off yet.

| Version | Environment | Backup verified | Migrations run | Smoke tests passed | Rollback ready | Approved by owner |
|---|---|---|---|---|---|---|
| Restore `main`, fix Railway config (2026-11-26) | Railway production | Not verified | Migration step not visible in logs; /health/ reports database ok | Backend `/health/` 200 database ok; frontend `/login` 200 | Not needed | Redeploy previous deployment from the Railway dashboard |

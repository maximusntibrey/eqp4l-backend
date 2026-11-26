# Deployment Log

No `v1.0.0` production release has been approved or completed. An unintended automatic deployment attempt occurred from `sprint/2-mvp-release` on 2026-11-26 before the verified-backup gate was satisfied. Auto-deploy is now disabled for both Railway services. Confirm backend migration state before any further deployment.

| Version | Environment | Backup verified | Migrations run | Smoke tests passed | Rollback ready | Approved by owner |
|---|---|---|---|---|---|---|
| Unintended partial auto-deploy (2026-11-26) | Railway production | No | Not confirmed; backend initialization/build/deploy did not start, with no evidence `preDeployCommand` ran | Frontend `/login` HTTP 200; backend `/health/` HTTP 502 | No | No; automatic trigger |

# Deployment Log

Railway deploys `main` to production and `develop` to staging, for both services. The owner waived the verified-backup gate for the first release (the database was empty).

| Version | Environment | Backup verified | Migrations run | Smoke tests passed | Rollback ready | Approved by owner |
|---|---|---|---|---|---|---|
| Restore `main`, port fix | Railway production | Waived by owner (empty database) | No: migrations missing, login returned 500 | Health ok, login 500, admin 500 | Redeploy previous deployment | Yes |
| Migrate and static fix (`06c7fcb`) | Railway production | Waived by owner (empty database) | Yes, all apps applied on start (`AUTO_MIGRATE=True`) | Health ok, bad-credential login 401, admin page 200, browser login reaches the API (401 for a wrong password) after the cookie fix | Yes: staging rehearsal below | Yes |
| Same commit | Railway staging | Not needed (no data) | Yes | Login, password change, dashboard, items, stock, branches, activity log and sales all 2xx | Rehearsed: previous commit deployed healthy, latest redeployed healthy, each switch under a minute | n/a |
| `v1.0.0` | Railway production | Waived by owner (empty database) | Yes | Authenticated screens verified on staging; production sign-in left to the first owner login | Yes | Yes |

Notes:
- Cookie fix: `CSRF_COOKIE_SAMESITE=None` and `SESSION_COOKIE_SAMESITE=None` on both environments. Without them the browser login returned 403 because frontend and backend are on different sites.
- The first Super Admin was created by the one-time bootstrap; the owner must sign in and change the one-time password.
- Not done: hosted backup and hosted restore test, Sentry (no DSN), real data load.

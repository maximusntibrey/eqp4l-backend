# Railway deployment

## Service settings

- Builder: Dockerfile (target `prod`, set by `railway.json`)
- Start: the image `CMD` runs `scripts/start.sh`: optional migrate (`AUTO_MIGRATE=True`), seed hook, then gunicorn on `$PORT`. `railway.json` sets no start or pre-deploy command, because Railway did not run the pre-deploy command.
- Static files are collected in the Docker build.
- Healthcheck path: `/health/`
- Environments: `production` deploys `main`, `staging` deploys `develop` (deployment trigger branch per environment).

## Variables

Set these on the Django service:

```text
DATABASE_URL=${{Postgres.DATABASE_URL}}
DJANGO_SECRET_KEY=<generate separately>
DJANGO_DEBUG=False
AUTO_MIGRATE=True
PORT=8080
DJANGO_ALLOWED_HOSTS=eqp4l-backend-production.up.railway.app,healthcheck.railway.app
CSRF_TRUSTED_ORIGINS=https://eqp4l-backend-production.up.railway.app,https://p4l-inventory-production.up.railway.app
CORS_ALLOWED_ORIGINS=https://p4l-inventory-production.up.railway.app
SECURE_PROXY_SSL_HEADER_ENABLED=True
SECURE_SSL_REDIRECT=True
CSRF_COOKIE_SAMESITE=None
SESSION_COOKIE_SAMESITE=None
SESSION_COOKIE_SECURE=True
CSRF_COOKIE_SECURE=True
MEDIA_ROOT=/data/media
```

The database service has internal hostname `postgres.railway.internal`. Prefer Railway's reference variable instead of pasting that hostname:
`DATABASE_URL=${{Postgres.DATABASE_URL}}`. Replace `Postgres` if the actual PostgreSQL service name differs.

Generate a Django secret locally:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(50))"
```

Never commit or print the generated value.

## Create the first production Super Admin

Either set `BOOTSTRAP_SUPERADMIN_NAME` once, read the one-time password from the deploy logs, then remove the variable. Or open a shell and run:

```text
python manage.py create_production_superadmin --full-name "Owner Name"
```

The command refuses reruns once a Super Admin exists and returns the Login ID plus a one-time password in the shell. Give the one-time password to the owner once, then require the owner to change it at first login.

## Railway Volume

Add a Railway Volume to the Django service and mount it at `/data`. Set `MEDIA_ROOT=/data/media`. Railway volumes persist across deploys and restarts. Django uses local `FileSystemStorage`; no object-storage credentials are required.

## Cross-site cookies

The frontend and backend run on different `up.railway.app` sites, so the session and CSRF cookies must be `SameSite=None; Secure`. Browsers that block third-party cookies will still fail; the long-term fix is one parent domain or serving `/api` from the frontend host.

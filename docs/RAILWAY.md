# Railway deployment

## Service settings

- Builder: Dockerfile
- Docker target: `prod`
- Start command: `gunicorn config.wsgi:application --bind 0.0.0.0:$PORT --workers 3`
- Pre-deploy: `python manage.py migrate --noinput && python manage.py collectstatic --noinput`
- Healthcheck path: `/health/`

The repository uses `railway.json`, so the dashboard can use the repo config directly.

## Variables

Set these on the Django service:

```text
DATABASE_URL=${{Postgres.DATABASE_URL}}
SECRET_KEY=<generate separately>
DEBUG=False
ALLOWED_HOSTS=eqp4l-backend-production.up.railway.app
CSRF_TRUSTED_ORIGINS=https://eqp4l-backend-production.up.railway.app,https://p4l-inventory-production.up.railway.app
CORS_ALLOWED_ORIGINS=https://p4l-inventory-production.up.railway.app
SECURE_PROXY_SSL_HEADER_ENABLED=True
SECURE_SSL_REDIRECT=True
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

## Railway Volume

Add a Railway Volume to the Django service and mount it at `/data`. Set `MEDIA_ROOT=/data/media`. Railway volumes persist across deploys and restarts. Django uses local `FileSystemStorage`; no object-storage credentials are required.

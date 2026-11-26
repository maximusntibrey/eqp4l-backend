FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
RUN useradd --create-home --uid 1000 app
COPY requirements.txt ./
RUN pip install --no-cache-dir --require-hashes -r requirements.txt

# Dev/CI image: adds test and check tools. Used by docker-compose.
FROM base AS dev
COPY requirements-dev.txt ./
RUN pip install --no-cache-dir --require-hashes -r requirements-dev.txt
COPY --chown=app:app . .
USER app
CMD ["bash", "scripts/start.sh"]

# Production image: runtime dependencies only.
FROM base AS prod
COPY --chown=app:app . .
RUN mkdir -p /app/staticfiles /app/media /data/media && chown -R app:app /app/staticfiles /app/media /data/media
USER app
# Static files are built into the image so the admin works without a pre-deploy step.
RUN DJANGO_SECRET_KEY=build-only DJANGO_DEBUG=False DATABASE_URL=postgres://build:build@localhost/build python manage.py collectstatic --noinput
CMD ["bash", "scripts/start.sh"]

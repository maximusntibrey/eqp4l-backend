# syntax=docker/dockerfile:1
# Django app image (O1.2). Multi-stage, non-root, base image pinned by digest.
# Dependencies come only from the hash-checked requirements/base.txt (production set).
# Host-agnostic: no cloud-specific tooling (O1.1 not decided).

# python:3.13-slim (3.13.18), digest verified 2026-11-19 (SKILLS.md Appendix A).
ARG PYTHON_IMAGE=python:3.13-slim@sha256:e48f59cdba69a3cbd9ed2cf0f348d90d45a8d350d98134cf1070bc106ee9ed90

FROM ${PYTHON_IMAGE} AS builder
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1
RUN python -m venv /opt/venv
COPY requirements/base.txt /tmp/base.txt
RUN /opt/venv/bin/python -m pip install --require-hashes -r /tmp/base.txt \
    && /opt/venv/bin/python -m pip check

FROM ${PYTHON_IMAGE} AS runtime
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --home-dir /app --shell /usr/sbin/nologin app
WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY manage.py ./
COPY eqp4l ./eqp4l
# Every project app (B2.1). A new app must be added here; tests/test_local_run.py checks
# that this list matches INSTALLED_APPS.
COPY accounts ./accounts
COPY audit ./audit
COPY branches ./branches
COPY inventory ./inventory
COPY roles ./roles
COPY sales ./sales
COPY stock_ledger ./stock_ledger
COPY transfers ./transfers
COPY warehouse ./warehouse
# Entrypoint: waits for the db, migrates, optional seed (FIX-1). sed strips any CR so a
# CRLF checkout on Windows still runs; .gitattributes also keeps it LF.
COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN sed -i 's/\r$//' /usr/local/bin/entrypoint.sh && chmod 0755 /usr/local/bin/entrypoint.sh
# Collect static files for WhiteNoise. The values are build-time dummies only (never
# secrets); real values come from the environment at run time.
RUN DJANGO_SECRET_KEY=build-only-not-a-secret DATABASE_URL=postgres://u:p@localhost/db \
    python manage.py collectstatic --noinput \
    && mkdir -p /app/.gunicorn \
    && chown -R app:app /app/staticfiles /app/.gunicorn
# Application code stays root-owned and read-only for the runtime user; only staticfiles
# and the gunicorn control-socket directory are writable by app.
USER app
EXPOSE 8000
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["gunicorn", "eqp4l.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "2", "--access-logfile", "-"]

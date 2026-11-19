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
COPY --chown=app:app manage.py ./
COPY --chown=app:app eqp4l ./eqp4l
# Collect static files for WhiteNoise. The values are build-time dummies only (never
# secrets); real values come from the environment at run time.
RUN DJANGO_SECRET_KEY=build-only-not-a-secret DATABASE_URL=postgres://u:p@localhost/db \
    python manage.py collectstatic --noinput \
    && chown -R app:app /app
USER app
EXPOSE 8000
CMD ["gunicorn", "eqp4l.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "2", "--access-logfile", "-"]

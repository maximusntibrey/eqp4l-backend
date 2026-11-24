# eqp4l-backend

Django REST API for the Payless4Laptops inventory and warehouse system. Requirements and plan: [docs/README.md](docs/README.md).
Python 3.12, Django 5.2 LTS, PostgreSQL 16. Everything runs in Docker; the host Python version does not matter.

## Run it locally (Windows)

1. Install Docker Desktop (WSL2 backend) and start it.
2. In PowerShell, from this folder:
   ```powershell
   .\scripts\dev.ps1 up
   ```
   This creates `.env` from `.env.example` (local-only values), builds the image, starts PostgreSQL 16 and the API, runs `migrate` and the seed hook automatically.
3. Open <http://localhost:8000/health/>. Expected: `{"status":"ok","database":"ok"}`.

Other tasks: `.\scripts\dev.ps1 check` (the full check command), `test`, `shell`, `logs`, `down`, `reset-db` (asks before deleting local data).
Without PowerShell: `docker compose up -d --build`, `docker compose run --rm web bash scripts/check.sh`, `docker compose down`.

## The one check command

```
docker compose run --rm web bash scripts/check.sh
```

Runs ruff (lint and format), mypy with django-stubs, bandit, pip-audit, `makemigrations --check`, `check --deploy`, then pytest with coverage (min 90%). CI runs the same script against a PostgreSQL service (`.github/workflows/ci.yml`).

## Deploy notes (host-agnostic)

- Item image upload (`PUT /items/{id}/image/`): the app refuses files over 5 MB with 413 `file_too_large`, but only after the body arrives. Set the reverse proxy or host body limit to about 6 MB (nginx `client_max_body_size 6m`) so oversized bodies are stopped early and a 5 MB image plus multipart overhead still passes.
- Uploaded images live under `MEDIA_ROOT` (env, default `./media`); give it a persistent disk or volume and serve `/media/` from the host (Django serves it only when DEBUG is on).
- Images are stored as uploaded: EXIF metadata (for example GPS) is NOT stripped. Re-encoding would change the bytes and quality, so it is left to a later decision.

## Changelog

- Contract 0.1.2 (not yet synced by the frontend), behaviour notes 2026-11-24, no schema change: `/me` `home_links` now has an Activity tile for Warehouse Admin and Branch Admin (OQ-25); the last active Super Admin cannot lose the role, be suspended or deactivated, answer 409 `conflict` (OQ-26); a Branch Admin's `/users/` list and detail also include Front Staff currently working at their branch (OQ-26).

## Dependencies

Pinned with pip-tools: edit `requirements.in` / `requirements-dev.in`, then `docker compose run --rm web bash scripts/compile-requirements.sh`. Every package is recorded in `docs/SKILLS.md` Appendix A.

## Status

- Skeleton only: `/health/`, settings, tooling. No models or migrations until the owner approves the permission table (`docs/design/PERMISSION_TABLE.md`) and the ERD (`docs/design/ERD.md`).
- `django.contrib.auth` and `AUTH_USER_MODEL` are added with the first migration (custom user from the start). See the note in `config/settings.py`.
- Seed: `scripts/seed.sh` is a no-op until models exist; it will create SA-0001, one dev user per role (passwords from `.env`), 3 branches and sample data, idempotently.
- OpenAPI: drf-spectacular is wired (`python manage.py spectacular --file schema.yaml`). The contract at `docs/api/openapi.yaml` is published only after owner approval (B1.3).

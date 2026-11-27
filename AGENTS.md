# AGENTS.md

Payless4Laptops inventory and warehouse system, backend: Django, DRF and PostgreSQL (eqp4l-backend).
The OpenAPI contract at `docs/api/openapi.yaml` is the only link to the frontend repo.

## Commands
- Check (lint, types, security, migrations, tests): `docker compose run --rm web bash scripts/check.sh`
- Run locally: `docker compose up`

## Deployment
- Production = Railway `main`. Staging = `develop`.
- `AUTO_MIGRATE=True` migrates on start, so every migration must be safe on existing data.

## Git rules
- Commit step by step: one logical change per commit.
- Clear messages in Conventional Commits form with the step id, e.g. `feat(branches): BT.1 expose branch_type`.
- Fixes and patches follow the same rules.
- Never commit secrets (`.env` stays git-ignored).
- No calendar dates in any plan or document.
- Keep frontend and backend changes in their own repos.
- Never force-push or rewrite history.
- Do not break live Railway deployments: migrations safe on existing data, build must pass before merging to `main`.
- Work on feature branches merged by pull request.
- Tick TASKS steps only after verification.

# eqp4l-backend

Django REST API for the Payless4Laptops Inventory & Warehouse System. It owns every business rule, permission and stock change. The React frontend lives in the separate repository `p4linventory-frontend`; the OpenAPI contract published from this repo is the only link between the two.

## Project documents

| File | What it is |
|---|---|
| [TASKS.md](TASKS.md) | Enforced rules, git workflow and the step list. Steps for this repo are ticked here |
| [SKILLS.md](SKILLS.md) | Technical standards, AI agent rules, and this repo's install register (Appendix A) |
| [docs/project/](docs/project/README.md) | Copies of the project requirements: overview, frontend, backend, DevOps, gaps, and background documents |

Precedence: `1-Overview-and-Sprints`, `2-Frontend-Requirements`, `3-Backend-Requirements` and `4-DevOps-Requirements` win; `TASKS.md` and `SKILLS.md` follow them; documents 5 and 6 are background only. The originals were PDF files; only the Markdown conversions are kept in git (no binaries).

## Status

Phase A (setup). No application code yet. The stack is Python 3.13, Django 5.2 LTS, Django REST Framework and PostgreSQL (TASKS section 2.3).

## Local setup (so far)

1. Set the git identity locally (TASKS 1.2).
2. Install the pre-commit hooks (lint and secret blocking, step T.3), see `SKILLS.md` Appendix A:

   ```
   pre-commit install --allow-missing-config
   pre-commit run --all-files
   ```

3. Copy `.env.example` to `.env` and fill in local values. `.env` is git-ignored. Never commit secrets.

The single check command (`scripts/check.sh`, step T.15) and Docker Compose (step O1.2) are added in later steps.

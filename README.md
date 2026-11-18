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

Sprint 1, tooling (B1.0). The stack is Python 3.13, Django 5.2 LTS, Django REST Framework and PostgreSQL (TASKS section 2.3). The Django project package is `eqp4l/`. There are no project apps, models or migrations yet: they wait for the owner's approval of the B1.2 ERD.

## Local setup

1. Set the git identity locally (TASKS 1.2).
2. Install the pre-commit hooks (lint and secret blocking, step T.3), see `SKILLS.md` Appendix A:

   ```
   pre-commit install --allow-missing-config
   pre-commit run --all-files
   ```

3. Create the virtual environment with Python 3.13 and install the pinned, hash-checked requirements (Git Bash on Windows shown; on Linux use `python3.13 -m venv .venv` and `.venv/bin/python`):

   ```
   py -V:3.13 -m venv .venv
   .venv/Scripts/python.exe -m pip install --require-hashes -r requirements/base.txt -r requirements/dev.txt
   ```

4. Start PostgreSQL (Docker Compose arrives in O1.2; until then):

   ```
   docker run -d --name eqp4l-pg -e POSTGRES_DB=eqp4l -e POSTGRES_USER=eqp4l -e POSTGRES_PASSWORD=change-me -p 127.0.0.1:5432:5432 postgres:18.7-alpine
   ```

5. Copy `.env.example` to `.env` and fill in local values. `.env` is git-ignored. Never commit secrets.
6. Run the single check command (lint, format, type check, security scans, migration check, tests):

   ```
   bash scripts/check.sh
   ```

To change a dependency, edit `requirements/base.in` or `requirements/dev.in` and re-run `pip-compile --generate-hashes --allow-unsafe --strip-extras` on it (base first). One dependency per branch, recorded in `SKILLS.md` Appendix A.

# Inventory & Warehouse System: Task List

> **Document set.** [README](README.md) · [1 Overview and Sprints](1-Overview-and-Sprints.md) · [2 Frontend](2-Frontend-Requirements.md) · [3 Backend](3-Backend-Requirements.md) · [4 DevOps](4-DevOps-Requirements.md) · [TASKS](TASKS.md) · [SKILLS](SKILLS.md) · [Gaps and actions](PROJECT_GAPS_AND_ACTIONS.md). Background only: [5 Detailed Requirements](5-Detailed-Requirements.md), [6 Functional Workflow Specification](6-Functional-Workflow-Specification.md).

## Overview

Source of truth for scope: the three requirements documents: [1-Overview-and-Sprints.md](1-Overview-and-Sprints.md), [3-Backend-Requirements.md](3-Backend-Requirements.md) and [2-Frontend-Requirements.md](2-Frontend-Requirements.md). DevOps steps come from [4-DevOps-Requirements.md](4-DevOps-Requirements.md) (proposed, awaiting owner approval). If this file and those documents disagree, the documents win. Stop and ask the owner before changing scope.

## Structure

- 9 sprints of 5 working days (45 days)
- Phase 1 = Sprints 1 to 5 (MVP released at end of Sprint 2, day 10)
- Phase 2 = Sprints 6 to 9
- Release tags: `sprint-1-demo` (Sprint 1, on `develop`), then `v1.0.0`, `v1.1.0`, `v1.2.0`, `v1.3.0` (Phase 1 complete), `v2.1.0`, `v2.2.0`, `v2.3.0`, `v2.4.0` (Phase 2 complete). See DevOps section 4.
- No calendar dates are attached to this plan. Work is tracked by sprint and day number only. Do not add dates.
- Stack: Django (backend, repo `eqp4l-backend`) and React (frontend, repo `p4linventory-frontend`).

## Important Deferrals

The following are NOT scheduled and should NOT be built (full list in the Deferrals section below and in Backend section 14):
- Barcode, label, scanning, per-piece records, serial numbers, POS integration, bundles, stocktake, repair tracking, email/SMS notifications, offline mode

## Sprint Structure

Step codes: `G` = git step, `T` = tooling step, `O` = DevOps step, `B<day>.<n>` = backend step, `F<day>.<n>` = frontend step.

Tick a box only when the step is done, tested, reviewed and pushed to git.

## 0. Enforced Rules

### 0.1 Orientation (do this before every piece of work)

1. Read this file, the requirements documents, and `SKILLS.md` in the repo you are working in.
2. Confirm which repo you are in: run `git remote -v` and `pwd`. Backend work happens only in the backend repo, frontend work only in the frontend repo. Never edit one repo while in the other. _(Applied in the end-of-day cycle (owner, 2026-11-23))_
3. Confirm the git identity (section 1.2) and the current branch: run `git config user.name`, `git config user.email`, `git branch --show-current`. Fix them before doing anything else. _(Applied in the end-of-day cycle (owner, 2026-11-23))_
4. Run `git pull` on the current branch, then pick the next unticked step in order. Do not skip ahead.
5. Always be present at the end of a step: after finishing, re-run the checks in 0.3, commit, push and tick. Never leave work uncommitted or unpushed when a session ends.

### 0.2 Scope rules

- Build only what the requirements documents describe, in the sprint they are scheduled. Deferred items (section 14 of [3-Backend-Requirements.md](3-Backend-Requirements.md)) stay out.
- Never invent business rules. If a rule is missing or unclear, add a note under "Open questions" at the bottom of this file and ask the owner.
- The frontend never decides a business rule. It shows what the API allows and reports what the API rejects. No business logic is duplicated in the frontend.
- The backend never depends on how screens look.
- The OpenAPI contract is the only link between the two repos. Change it only by: propose, agree with the owner, update the contract file, then adjust both sides. Breaking changes only at a sprint boundary.

### 0.3 Quality rules (a step is not done until all pass)

- Code works and the step's tests exist and pass. Run the repo's single check command (lint, type check, tests) and it must be green.
- Every stock change goes through the one stock service (atomic, row-locked, with a ledger entry). Never edit balances directly.
- The audit trail and the stock ledger are append-only. Never write code that edits or deletes them.
- Permissions are enforced on the server for every protected action (role, active branch, approved access).
- Secrets never go in code or in git. Use environment variables. `.env` files are git-ignored.
- Cost price is visible only to SuperAdmin and Warehouse Admin. Cross-branch lookup shows branch name and quantity only.
- Timestamps are timezone-aware and shown in Africa/Accra time (storing in UTC is proposed, see `SKILLS.md`). Currency is GHS.
- Frontend: 360 px width with no sideways scroll, tap targets at least 44 px, every icon has a text label, status never shown by colour alone, keyboard navigation works.
- Do not mark a step done on partial work. If blocked, leave it unticked and note the blocker under "Open questions".

### 0.4 Honesty and safety rules

- Never claim a test passed, a command ran, or a deployment succeeded unless it did. Report real output.
- Never use destructive commands (`git push --force`, `git reset --hard` on shared branches, dropping databases, deleting files) without the owner's explicit approval.
- Production deployment (Day 10) and any production data change need the owner's go-ahead first.
- Do not install a package or skill that has not been vetted (section 2.1). Record every install in `SKILLS.md`.
- Keep this file current: tick completed steps in the same commit as the work.

### 0.5 Fixes, patches and updates (these follow ALL the rules above, especially the git rules)

A fix, patch, dependency update, config change or "quick tweak" is real work. It gets no shortcut. Section 1.7 gives the exact git procedure.

- Never edit directly on `main`, `develop` or a sprint branch. Every change, however small, goes on its own branch and merges by pull request. _(Applied in the end-of-day cycle (owner, 2026-11-23))_
- Every fix is tied to a reference: a step code, or a logged issue (`FIX-<n>`) recorded under "Fix log" at the bottom of this file. No untracked changes.
- A bug fix must include a test that fails before the fix and passes after it. If a test is genuinely impossible, record why in the pull request.
- The full check command must be green before the pull request is opened and again before it merges.
- Fixes touching stock, ledger, permissions, audit, money or migrations need extra care: re-run the permission and branch-isolation tests and the concurrency tests, and never edit an existing migration that has been applied. Add a new migration instead. _(git parts: applied in the end-of-day cycle (owner, 2026-11-23))_
- Dependency updates: one dependency (or one tightly related group) per branch, pinned, with the lockfile updated, the security scan re-run, and `SKILLS.md` updated.
- A change that alters the OpenAPI contract follows the contract rule in 0.2 and is never mixed with an unrelated fix.
- Urgent production problems use the `hotfix/` procedure in 1.7. Urgency is not a reason to skip tests, review or the backup in 0.6.
- Never rewrite published history to hide a mistake. Fix forward with a new commit, or revert with `git revert`.

### 0.6 DevOps rules

- Environments are `local`, `staging` and `production`. Code reaches production only through `main`, by tag, after passing staging.
- Staging mirrors production (same database engine, same settings apart from secrets and domains). Never test migrations first on production.
- Take a verified backup before every production deployment and every production migration. Record it in the deployment log.
- Every deployment has a written rollback step that has been tried on staging. If the rollback is not known to work, do not deploy.
- Secrets live only in the hosting platform's secret store or environment variables. They are never in git, logs, screenshots or chat.
- Deploy only with the owner's go-ahead for production. Report real deployment output. Never claim a deploy worked without running the smoke tests (section 3).
- Infrastructure and deployment configuration live in git in the repo they belong to, and change by pull request like code.

### 0.7 Development gate

- No application code is written until the owner authorises development. Record the authorisation (who, when, which sprint) under "Open questions" below and in `PROJECT_GAPS_AND_ACTIONS.md`.
- Before authorising, the owner answers the critical gaps (GAP-C01 to GAP-C08) in `PROJECT_GAPS_AND_ACTIONS.md`, or states which can wait and until when.
- Gate confirmed by the owner on 2026-11-18. All critical gaps (GAP-C01 to GAP-C08) were answered the same day. Current status: **authorised by the owner on 2026-11-18, starting with Sprint 1.** Rule 0.1 still applies before every piece of work, and section 2 (T.0: package installs must work) comes before any code.

## 1. Git Workflow (Two Separate Repositories) _(Applied in the end-of-day cycle (owner, 2026-11-23))_

### 1.1 Repositories

| Part | Repository | Owner |
|---|---|---|
| Backend | `eqp4l-backend` | maximusntibrey |
| Frontend | `p4linventory-frontend` | maximusntibrey |

The backend repository name `eqp4l-backend` is confirmed by the owner. Do not create or rename repos without approval.

### 1.2 Identity (set locally in each repo, never globally)

```
git config user.name  "maximusntibrey"
git config user.email "maximuslambertntibrey.mln@gmail.com"
```

Check it at the start of every session (rule 0.1). Commits made under any other identity must be fixed before pushing.

### 1.3 Branch model (same in both repos)

- `main`: production-ready code only. Tagged for each release. Protected: no direct commits, no force pushes.
- `develop`: integration branch. Deployed to staging. All sprint work merges here.
- `sprint/<n>-<slug>`: one per sprint, branched from `develop`.
- `feature/<step-code>-<slug>`: one per step or small group of steps, branched from the sprint branch.
- `fix/<slug>`: bug fixes. `hotfix/<slug>`: urgent production fixes, branched from `main`.

### 1.4 Commit and pull request rules

- One commit per completed step, or smaller. Format: `<type>(<step-code>): <what changed>` where type is `feat`, `fix`, `test`, `docs`, `chore` or `refactor`.
- Commit often, push at least at the end of every step. No giant end-of-day commits.
- Each feature branch is merged into its sprint branch by pull request, only after the check command is green. Tick the step's box in `TASKS.md` in the same PR.
- At sprint end the sprint branch is merged into `develop` (staging check), then `develop` into `main` and tagged (release sprints only).
- Delete merged feature branches. Never commit secrets, `.env`, build output, or large binaries.

### 1.5 Per-sprint git routine

Start of sprint:
1. `git checkout develop && git pull`
2. `git checkout -b sprint/<n>-<slug>` and `git push -u origin sprint/<n>-<slug>`

Every step:
3. `git checkout -b feature/<code>-<slug>` from the sprint branch
4. Do the work, run the check command, commit, push, open a pull request into the sprint branch, merge, tick the box

End of sprint:
5. Pull the latest `develop` into the sprint branch, fix conflicts, run the full check command
6. Pull request: sprint branch into `develop`, then run the staging integration check (frontend against real backend)
7. Release sprints only: pull request `develop` into `main`, tag it, push the tag, write release notes
8. Update docs and `SKILLS.md`, tick the sprint's git steps, push

### 1.6 Initial git setup _(Applied in the end-of-day cycle (owner, 2026-11-23))_

- [x] G.1 Backend repo `eqp4l-backend`: clone, set identity (1.2), create `main` and `develop`, protect `main`
- [x] G.2 Frontend repo `p4linventory-frontend`: clone, set identity (1.2), create `main` and `develop`, protect `main`
- [x] G.3 Add `.gitignore`, `.env.example`, `README.md`, `SKILLS.md` and a copy of this `TASKS.md` to both repos
- [x] G.4 Add a pull request template with the quality checklist from rule 0.3 to both repos
- [x] G.5 Add CI to both repos that runs the check command on every pull request (done again in B1.8 and F1.2; tick here when the repos are connected)
- [x] G.6 Branch protection on `main` and `develop` in both repos: pull request required, CI green required, no force pushes, no direct commits

### 1.7 Git procedure for fixes, patches and updates

Normal fix (not urgent, found during a sprint or on staging):
1. Log it under "Fix log" with a `FIX-<n>` reference. 2. `git checkout <sprint branch or develop> && git pull`. 3. `git checkout -b fix/<fix-ref>-<slug>`. 4. Write the failing test, make the fix, run the check command. 5. Commit as `fix(FIX-<n>): <what changed>`, push, open a pull request. 6. Merge only when CI is green, then delete the branch. 7. Tick or update the Fix log entry in the same pull request.

Dependency or config update:
1. `git checkout develop && git pull`. 2. `git checkout -b chore/<slug>`. 3. Update one dependency or group, update the lockfile, run the check command and the security scan. 4. Commit as `chore(<ref>): <what changed>`, update `SKILLS.md`, push, pull request, merge when green.

Hotfix (production is broken or unsafe):
1. Tell the owner and get the go-ahead. 2. Take a verified backup (rule 0.6). 3. `git checkout main && git pull`, then `git checkout -b hotfix/<fix-ref>-<slug>`. 4. Failing test, fix, full check command. 5. Pull request into `main`, merge when green, tag a patch version, deploy, run the smoke tests. 6. Merge the same fix back into `develop` and into the open sprint branch by pull request so it is not lost. 7. Record it in the Fix log and the deployment log.

After any merge: confirm the other repo is not affected. If the OpenAPI contract changed, create the matching task in the other repo before closing the fix.

Commit message ending: when an AI assistant makes a commit or pull request, keep the author identity from 1.2 and follow any attribution lines the owner has asked for.

## 2. SKILLS, TOOLS AND PACKAGES TO INSTALL (Day 1, before any code)

### 2.1 Install procedure for every item

1. Check whether it is already installed. 2. Vet it: official source, maintained, licence acceptable, no known security issues. 3. Install a pinned version. 4. Verify it works (run version command or a smoke test). 5. Record name, version, purpose and date in `SKILLS.md` in the right repo. 6. Commit `SKILLS.md` and lockfiles.

Package installs need network access to the package registries (PyPI, npm, GitHub). In the Claude workspace this is controlled by the account's network settings, which an AI cannot change. If installs are refused, stop, tell the owner, and do not fake the install. Step T.0 below makes sure installs work before Sprint 1 starts.

### 2.2 Shared

- [x] T.0 Confirm package installs work in the working environment: run a test install of one Python package (`pip install`) and one npm package. If refused, the owner updates the network settings to allow package registries, opens a new chat or session (an existing one may not pick up the change), and the test is repeated. Do not continue until it passes.
- [x] T.1 Git, GitHub CLI (`gh`) and authentication as maximusntibrey
- [ ] T.2 Claude skills available to the AI: `docx`, `pdf`, `xlsx` (user guides, exports, report checks), `frontend-design` (UI work), `file-reading` and `pdf-reading` (reading the requirements PDFs), `skill-creator` (only if a project skill is needed)
- [x] T.3 Editor config (`.editorconfig`), pre-commit hooks to run lint and block secrets
- [x] T.4 Create `SKILLS.md` in both repos and record every install

### 2.3 Backend (Python, Django, API, database)

- [x] T.5 Python 3.12+, `venv`, `pip`/`pip-tools` (pinned requirements)
- [x] T.6 Django and Django REST Framework (custom user model, session login)
- [x] T.7 `drf-spectacular` (generates the OpenAPI contract)
- [x] T.8 PostgreSQL (and `psycopg`), plus `django-environ` (env config)
- [x] T.9 Password hashing (Argon2 via `argon2-cffi`), `django-ratelimit` or DRF throttling
- [x] T.10 `django-cors-headers`, `django-filter`, `Pillow` (image validation and optimisation)
- [x] T.11 `pytest`, `pytest-django`, `factory-boy`, `pytest-cov` (permissions, isolation, concurrency tests)
- [x] T.12 `ruff` (lint and format), `mypy` or `django-stubs`, `bandit` and `pip-audit` (security checks)
- [x] T.13 Gunicorn and WhiteNoise (or the chosen host's equivalent), Sentry SDK (error monitoring)
- [x] T.14 Backup tooling: `pg_dump` and a scripted restore test
- [x] T.15 One check command (e.g. `make check`) that runs lint, type check, security scan and tests

### 2.4 Frontend (React, mobile-first UI)

- [ ] T.16 Node.js LTS and `npm` (or `pnpm`), pinned in `.nvmrc`
- [ ] T.17 React with TypeScript and Vite
- [ ] T.18 React Router, TanStack Query (data fetching), `react-hook-form` with `zod` (forms and inline validation)
- [ ] T.19 Tailwind CSS (or the chosen CSS approach) with the design tokens from Frontend section 2; Lucide icons (`lucide-react`)
- [ ] T.20 `openapi-typescript` and a typed API client generated from the backend contract
- [ ] T.21 MSW (Mock Service Worker) for mock responses in CI and early development
- [ ] T.22 Vitest, React Testing Library, Playwright (end-to-end smoke tests), `axe-core` / `vitest-axe` (accessibility checks)
- [ ] T.23 ESLint and Prettier, `eslint-plugin-jsx-a11y`, `npm audit`
- [ ] T.24 One check command (e.g. `npm run check`) that runs lint, type check, unit tests and build

## 3. DEVOPS PLAN

DevOps covers hosting, environments, CI/CD, database operations, backups, monitoring, security and releases for both repos. The requirements say the project has no established setup, so time is reserved for it in every sprint (the `O` steps inside each sprint). All DevOps work follows rules 0.5 and 0.6 and the git procedure in 1.7.

### 3.1 Environments

| Environment | Purpose | Deployed from | Who approves |
|---|---|---|---|
| local | Developer machine, Docker Compose (Django, PostgreSQL) and Vite dev server | any branch | none |
| staging | Integration check: frontend against real backend, end-to-end tests, migration rehearsal | `develop`, automatically on merge | none |
| production | Real users and real data | `main`, by version tag only | owner's go-ahead for every release |

### 3.2 Target architecture

- Backend: Django served by Gunicorn behind the host's HTTPS reverse proxy. PostgreSQL as a managed database.
- Frontend: React production build served as static files (static host or CDN) over HTTPS.
- Product images and uploaded documents: object storage (not the server disk), included in backups.
- Scheduled jobs (overdue transfer reminders, backups): run by the host's scheduler or cron calling Django management commands.
- Health: a `/health/` endpoint on the backend that checks the app and the database.

### 3.3 CI/CD pipeline

Every pull request runs the check command in CI and must be green before merge. Pipeline details (what each CI run checks, staging and production deploys) are in DevOps section 5.

### 3.4 Smoke tests

1. `/health/` responds OK. 2. Log in as the SuperAdmin. 3. Open the dashboard and the item list. 4. Stock screen loads. 5. A read-only Find search returns results. 6. HTTPS, CORS and secure cookie settings are correct. 7. No new errors in monitoring after 15 minutes.

### 3.5 Backups and recovery

- Automated daily database backups plus object-storage backups, with a stated retention period.
- A restore test is done on staging before the MVP release, after any major migration, and at each phase end.
- A verified backup is taken immediately before every production deployment and logged.

## PHASE 1

## SPRINT 1 (Days 1 to 5): MVP part 1. Goal: setup, login, users and branches, items and stock, warehouse flow. No release; demo only.

Branches: `sprint/1-foundations` in both repos. Tag at end: `sprint-1-demo` (on `develop`, no release to `main`).

### Git steps for Sprint 1 _(Applied in the end-of-day cycle (owner, 2026-11-23))_

- [x] S1.G1 Backend: create `sprint/1-foundations` from `develop`, push
- [x] S1.G2 Frontend: create `sprint/1-foundations` from `develop`, push
- [ ] S1.G3 Backend: all Sprint 1 steps merged by pull request into the sprint branch, one commit per step
- [ ] S1.G4 Frontend: all Sprint 1 steps merged by pull request into the sprint branch, one commit per step
- [ ] S1.G5 Both repos: sprint branch merged into `develop`, staging integration check passed
- [ ] S1.G6 Both repos: tag `sprint-1-demo`, docs and `SKILLS.md` updated, everything pushed

### Sprint 1 standards

- [ ] S1.S1 Tests added for every new feature; security check on new features; backup check; docs updated; 10 to 20% of time kept free for bugs

### Backend, Sprint 1

- [x] B1.0 Tooling setup and verification (section 2.2 and 2.3), recorded in `SKILLS.md`
- [x] B1.1 Scope and permission table for owner approval (4 roles: SuperAdmin, Warehouse Admin, Branch Admin, Front Staff; per-person permissions: Receive stock, Manage prices, discount; branch rules; self-approval rules; shortfall resolution by admin roles only)
- [x] B1.2 Data model: users, roles, branches, items, stock balances, stock movements, dispatches, sales (ERD written and approved by the owner before any migration, see `SKILLS.md` Database Standards; stock buckets and movements per Specification section 11.2; ledger rows carry a stable source reference and line ID so per-unit tracking can be added later, no unit tables now)
- [x] B1.3 Endpoint list as the API contract (OpenAPI), published first for the frontend
- [x] B1.4 Short requirements digest in the repo
- [x] B1.8 Repo, environments, CI and the one check command
- [x] B2.1 Schema and migrations (accounts, roles, branches, inventory, stock, ledger, audit)
- [x] B2.2 User model and ID generator (`SA-0001` for SuperAdmins, `USR-0001` for others; never changed, never reused)
- [x] B2.3 Login, logout, password hashing, secure sessions, rate limit and login log
- [x] B2.4 Permission checks by role and branch (only SuperAdmins can assign multiple roles)
- [x] B2.5 Seed data: `SA-0001`, 3 branches, sample items with stock
- [x] B2.6 Tests: IDs, login, permissions
- [x] B3.1 Working-branch selection and switching endpoints (every switch logged; requests scoped to the chosen branch)
- [x] B3.2 Branch management API (create, edit, deactivate)
- [x] B3.3 User management API (auto ID, role, branch, deactivate, reset password, grant per-person permissions such as Receive stock)
- [x] B3.4 Dashboard shell data
- [x] B3.5 Tests: branch scoping and access
- [x] B4.1 Item API: common fields, key specs, draft or active, with item field definitions per category
- [x] B4.2 One image upload (type and size enforced)
- [x] B4.3 Stock balances and the movement log: one service for every stock change, atomic with row locks and idempotency keys. Required tests (FIX-1, FIX-2, FIX-9, see ERD s4): user B replaying user A's key never gets A's stored body; same key with another body returns 409 `idempotency_conflict`; sale line cost snapshot is 4 dp in the DB, 2 dp in the API, absent for BA/FS; the same csv_import batch row posted twice writes one ledger row.
- [x] B4.4 Stock query API
- [x] B4.5 Tests: validation rules, no negative stock, atomic stock service
- [x] B5.1 Warehouse receipt API (supplier name, items, quantities, cost; atomic with ledger; duplicate submissions blocked)
- [x] B5.2 Dispatch API (Warehouse Admin only; validates available stock; quantities go in transit)
- [x] B5.3 Branch receiving API (quantity per line, approve all, partial or reject; shortfall flagged)
- [x] B5.4 Queries for what is waiting at each branch
- [x] B5.5 Tests: receipt atomicity, dispatch permissions, partial receiving
- [x] B5.6 Sprint 1 review, fixes and publish the updated OpenAPI contract

### Frontend, Sprint 1

- [ ] F1.0 Tooling setup and verification (section 2.2 and 2.4), recorded in `SKILLS.md`
- [ ] F1.1 UI kit: colours (white, grey, one accent; green/amber/red for status only), spacing, one icon set, buttons, cards, form fields, status badges, top bar, navigation
- [ ] F1.2 Repo, environments, CI and the one check command
- [ ] F1.3 App shell
- [ ] F1.4 API client generated from the contract, with mock responses
- [ ] F2.1 Login screen (user ID, password, clear errors, too-many-attempts message)
- [ ] F2.2 Layout, route guards and menu per role (built from what the API allows, max 5 items per role; Super Admin: Home, Items, Warehouse, Branches, Users, with Activity, Sell, Find and Receive opened from Home)
- [ ] F2.3 Tests: login and route guards
- [ ] F3.1 Working-branch selection and switching (top bar shows branch, ID, switch icon with label, logout)
- [ ] F3.2 Branch management screens
- [ ] F3.3 User management screens (show the generated ID after creation; deactivate and reset password with confirm step; per-person permissions such as Receive stock)
- [ ] F3.4 Dashboard shell
- [ ] F4.1 Item list (search, filters, pagination, status badges, cards on phones; cost shown only if the API returns it)
- [ ] F4.2 Item add and edit (category-driven form from field definitions, inline validation, save as Draft, activate, duplicate warning)
- [ ] F4.3 One image upload with clear type and size messages
- [ ] F4.4 Stock screen (by location, low-stock flag, search)
- [ ] F4.5 Tests: item form and validation
- [ ] F5.1 Receive stock into the warehouse screen (supplier, item lines, review, confirm, receipt reference shown)
- [ ] F5.2 Dispatch screen (branch, lines with available quantity, status list)
- [ ] F5.3 Branch receiving screen (waiting list, quantity pre-filled, "Received all" shortcut, shortfall note and highlight)
- [ ] F5.4 Screens for what is waiting at each branch
- [ ] F5.5 Tests: receiving flow
- [ ] F5.6 Sprint 1 review, 360 px check and fixes

### DevOps, Sprint 1

- [ ] O1.1 Owner chooses the hosting provider, database host, object storage and domain names (record in `RUNBOOK.md` and remove from Open questions)
- [x] O1.2 Local environment: Dockerfile and Docker Compose for the backend and PostgreSQL; `.env.example` for both repos
- [x] O1.3 Backend CI pipeline (3.3) with a PostgreSQL service — verified `.github/workflows/ci.yml` and green manual CI runs
- [x] O1.4 Frontend CI pipeline (3.3) — verified frontend `.github/workflows/ci.yml` and green manual CI runs
- [ ] O1.5 Staging environment created for backend and frontend, secrets stored in the host's secret store
- [ ] O1.6 Automatic deploy of `develop` to staging, followed by the smoke tests (3.4)
- [ ] O1.7 `/health/` endpoint and Sentry connected on staging
- [ ] O1.8 Branch protection and secret scanning confirmed in both repos (G.6)

## SPRINT 2 (Days 6 to 10): MVP part 2. Goal: sales, find, CSV import, dashboard and activity log, testing, hardening, deployment. Release: MVP (day 10).

Branches: `sprint/2-mvp-release` in both repos. Tag at end: `v1.0.0` (MVP) on `main` in both repos.

### Git steps for Sprint 2 _(Applied in the end-of-day cycle (owner, 2026-11-23))_

- [ ] S2.G1 Backend: create `sprint/2-mvp-release` from `develop`, push
- [ ] S2.G2 Frontend: create `sprint/2-mvp-release` from `develop`, push
- [ ] S2.G3 Backend: all Sprint 2 steps merged by pull request, one commit per step
- [ ] S2.G4 Frontend: all Sprint 2 steps merged by pull request, one commit per step
- [ ] S2.G5 Both repos: sprint branch merged into `develop`, staging integration check passed
- [ ] S2.G6 Owner go-ahead received, then `develop` merged into `main` in both repos
- [ ] S2.G7 Tag `v1.0.0` (MVP) in both repos, release notes written, pushed
- [ ] S2.G8 Docs and `SKILLS.md` updated, everything pushed

- [ ] S2.S1 Sprint standards (tests, security check, backup check, docs, 10 to 20% buffer)

### Backend, Sprint 2

- [x] B6.1 Sale API (price from the item, payment method, stock deducted, overselling blocked; sale, deduction, ledger and audit atomic)
- [x] B6.2 Sales list per branch
- [x] B6.3 Find and search API including other branches' quantities (branch name and quantity only)
- [x] B6.4 CSV import API (items and opening quantity per location, dry run, error report with row numbers, opening balances written as ledger movements)
- [x] B6.5 Cancel sale API (SuperAdmin and Branch Admin, reason required, reversal entry linked to the original; status becomes Cancelled)
- [x] B6.6 Tests: sale atomicity, overselling, cancel reversal, import
- [x] B7.1 Dashboard endpoints (stock per branch, in transit, low stock, scoped to role and branch)
- [x] B7.2 Activity log endpoints (filter by user, branch, action, date)
- [x] B7.3 Basic discrepancy resolution for dispatch shortfalls: return to sender, confirm loss, record damage; mandatory note; through the stock service with ledger and audit entries; any admin role (Super Admin, Warehouse Admin, Branch Admin) within its allowed branches; front staff refused
- [x] B7.4 Tests: each resolution path, balances and ledger after resolution, permission refusals
- [x] B8.1 End-to-end tests (receive, dispatch, branch receive, sell, find)
- [x] B8.2 Permission and branch-isolation tests (allowing the cross-branch lookup exception)
- [x] B8.3 Bug fixes from testing
- [x] B9.1 Performance check (search and product list within about 2 seconds) — verified `tests/test_b9.py` at 250 seeded items
- [x] B9.2 Security check of the MVP endpoints — verified `tests/test_contract_security.py`, `tests/test_permissions.py`, and `tests/test_b9.py`
- [ ] B9.3 Automated backups and a tested restore — local backup/restore verified; automated hosting backups remain blocked by O1.1
- [x] B9.4 Fixes from the checks — no new stock, permission or security finding required a fix
- [ ] B10.1 Production deployment (after the owner's go-ahead)
- [ ] B10.2 Load real data and create real users
- [x] B10.3 Short admin notes — `docs/ADMIN_NOTES.md`
- [ ] B10.4 MVP release (v1.0.0) — blocked by hosting/staging, production backup and owner go-ahead

### Frontend, Sprint 2

- [ ] F6.1 Sell screen (search, quantities, running list and total, payment method, confirm in about 3 steps, clear message when quantity exceeds stock)
- [ ] F6.2 Sales list and cancel action (reason asked, confirm step, cancelled badge)
- [ ] F6.3 Find screen (stock at my branch plus other branches by name and quantity only)
- [ ] F6.4 CSV import screen (upload, preview, error report with row numbers, confirm)
- [ ] F6.5 Tests: sell flow
- [ ] F7.1 Dashboards (a few big numbers and a short recent-activity list, no charts)
- [ ] F7.2 Activity log screen (filter by user, branch, action, date), opened from Home for Super Admin
- [ ] F7.3 Shortfall list and resolve screen (return to sender, confirm loss, record damage; note required; confirm step)
- [ ] F8.1 Component tests (item form, lists and filters, sell flow, receiving flow)
- [ ] F8.2 End-to-end smoke test against staging (login, pick branch, add item, receive, dispatch, receive at branch, sell, find)
- [ ] F8.3 Bug fixes from testing
- [x] F9.1 UI consistency pass — verified by `e2e/f9.spec.ts` and existing 360 px Playwright coverage
- [x] F9.2 Accessibility check (360 px, 44 px targets, labels on every icon, keyboard-only flows) — verified by `e2e/f9.spec.ts`, component axe tests and Playwright 360 px suites
- [x] F9.3 List performance check and fixes — verified `e2e/f9.spec.ts`; no fix was required
- [ ] F10.1 Short user guide and walkthrough (use the `docx` or `pdf` skill)
- [ ] F10.2 Checks on the live frontend
- [ ] F10.3 MVP release (v1.0.0)

### DevOps, Sprint 2

- [ ] O2.1 Production environment created (managed PostgreSQL, object storage, HTTPS, domains, CORS and CSRF settings, secure cookies)
- [ ] O2.2 Automated daily backups for the database and the image storage
- [ ] O2.3 Restore test on staging, result recorded in the deployment log
- [ ] O2.4 Rollback rehearsed on staging, written into `RUNBOOK.md`
- [ ] O2.5 Monitoring and uptime checks on production
- [ ] O2.6 Owner go-ahead, verified backup, then production deployment of `v1.0.0` with smoke tests (matches B10.1)
- [ ] O2.7 Deployment log entry written for `v1.0.0`

## SPRINT 3 (Days 11 to 15): Fixes from real use, laptop, parts and accessory specifications, warranty terms, product and variant split, several images and spec sheets. Release: `v1.1.0`.

Branches: `sprint/3-specifications` in both repos. Tag at end: `v1.1.0` on `main` in both repos.

### Git steps for Sprint 3 _(Applied in the end-of-day cycle (owner, 2026-11-23))_

- [ ] S3.G1 Backend: create `sprint/3-specifications` from `develop`, push
- [ ] S3.G2 Frontend: create `sprint/3-specifications` from `develop`, push
- [ ] S3.G3 Both repos: all Sprint 3 steps merged by pull request, one commit per step
- [ ] S3.G4 Both repos: sprint branch merged into `develop`, staging integration check passed
- [ ] S3.G5 Owner go-ahead, verified backup, `develop` merged into `main`, tag `v1.1.0`, release notes, docs and `SKILLS.md` updated, pushed

- [ ] S3.S1 Sprint standards (tests, security check, backup check, docs, 10 to 20% buffer)

### Backend, Sprint 3

- [ ] B11.1 Fixes from real use (data, performance)
- [ ] B11.2 Scheduled daily backups confirmed (matches O3.1)
- [ ] B12.1 Typed laptop specification fields (Backend 3.3) with validation and filter columns
- [ ] B12.2 Laptop filters: processor, RAM, storage, screen size, operating system
- [ ] B13.1 Part specifications (Backend 3.4), common and type-specific fields
- [ ] B13.2 Compatibility catalogue (many-to-many to laptop brand, series, model; replaced part numbers)
- [ ] B13.3 "Parts for laptop model X" search
- [ ] B14.1 Accessory specifications (Backend 3.5) and filters
- [ ] B14.2 Warranty terms on items (type, months) and warranty end date calculated on each sale line
- [ ] B14.3 Tests: field definitions per category, validation, filters, warranty end date
- [ ] B15.1 Split items into product and variant, with data migration (rehearsed on staging first, O3.2)
- [ ] B15.2 Several images per product with a primary image; spec-sheet attachments (type and size enforced, hidden not deleted once there is history)
- [ ] B15.3 Tests: migration keeps balances, ledger and history intact; image and document rules
- [ ] B15.4 Sprint 3 review, publish the updated OpenAPI contract, release `v1.1.0`

### Frontend, Sprint 3

- [ ] F11.1 Fixes from real MVP use and UI polish from feedback
- [ ] F12.1 Laptop specification form sections and laptop filters
- [ ] F13.1 Part specification forms, compatibility picker, "parts for laptop model X" search
- [ ] F14.1 Accessory forms and filters
- [ ] F14.2 Warranty terms on the item form; warranty end date on the sale and in the sales list
- [ ] F15.1 Product and variant screens
- [ ] F15.2 Several images with a primary image, and spec-sheet upload
- [ ] F15.3 Tests: category-driven forms for all three categories, warranty terms, images; 360 px check
- [ ] F15.4 Release `v1.1.0`

### DevOps, Sprint 3

- [ ] O3.1 Scheduled backups confirmed
- [ ] O3.2 Product and variant migration rehearsed on staging with rollback tested
- [ ] O3.3 Verified backup, deploy, smoke tests, deployment log entry

## SPRINT 4 (Days 16 to 20): Branch-to-branch transfers, stock adjustments and reversals, notifications. Release: `v1.2.0`.

Branches: `sprint/4-transfers` in both repos. Tag at end: `v1.2.0` on `main` in both repos.

### Git steps for Sprint 4 _(Applied in the end-of-day cycle (owner, 2026-11-23))_

- [ ] S4.G1 Backend: create `sprint/4-transfers` from `develop`, push
- [ ] S4.G2 Frontend: create `sprint/4-transfers` from `develop`, push
- [ ] S4.G3 Both repos: all Sprint 4 steps merged by pull request, one commit per step
- [ ] S4.G4 Both repos: sprint branch merged into `develop`, staging integration check passed
- [ ] S4.G5 Owner go-ahead, verified backup, `develop` merged into `main`, tag `v1.2.0`, release notes, docs and `SKILLS.md` updated, pushed

- [ ] S4.S1 Sprint standards (tests, security check, backup check, docs, 10 to 20% buffer)

### Backend, Sprint 4

- [ ] B16.1 Branch-to-branch transfer API: create with reason, validate and reserve, in transit (Branch Admin)
- [ ] B17.1 Transfer receiving: quantity per line, approve all, partial or reject; sender cannot approve
- [ ] B17.2 Extend the Sprint 2 discrepancy resolution (B7.3) to branch-to-branch transfers, plus other authorised dispositions
- [ ] B17.3 Tests: transfer permissions, partial receipt, discrepancy resolution, in-transit stock not sellable
- [ ] B18.1 Stock adjustments (damaged, expired, count variance, found stock, entry correction, restockable return) with mandatory reason and approval
- [ ] B18.2 Reversals as linked compensating movements; self-approval rule (Super Admin flagged)
- [ ] B18.3 Tests: adjustments, reversals, approval rules
- [ ] B19.1 Notifications (incoming stock, shortfalls, low stock, pending approvals) and their API
- [ ] B19.2 Overdue-transfer reminder job (configurable, suggested 48 hours), run by the O4.1 scheduler
- [ ] B20.1 Buffer, regression, publish the updated OpenAPI contract, release `v1.2.0`

### Frontend, Sprint 4

- [ ] F16.1 Branch transfer screen: send
- [ ] F17.1 Branch transfer screen: receive, with shortfalls and discrepancy resolution
- [ ] F18.1 Stock adjustment and reversal screens with approval
- [ ] F19.1 Notification centre and badge (bell icon with a text label)
- [ ] F20.1 Buffer, regression and release `v1.2.0`

### DevOps, Sprint 4

- [ ] O4.1 Scheduler for the overdue transfer reminder on staging and production
- [ ] O4.2 Concurrency tests at staging data volume
- [ ] O4.3 Verified backup, deploy, smoke tests, deployment log entry

## SPRINT 5 (Days 21 to 25): Branch access requests, multi-role assignment, price history, activity screens, security review and hardening. Release: `v1.3.0` (Phase 1 complete).

Branches: `sprint/5-phase1-complete` in both repos. Tag at end: `v1.3.0` on `main` in both repos.

### Git steps for Sprint 5 _(Applied in the end-of-day cycle (owner, 2026-11-23))_

- [ ] S5.G1 Backend: create `sprint/5-phase1-complete` from `develop`, push
- [ ] S5.G2 Frontend: create `sprint/5-phase1-complete` from `develop`, push
- [ ] S5.G3 Both repos: all Sprint 5 steps merged by pull request, one commit per step
- [ ] S5.G4 Both repos: sprint branch merged into `develop`, staging integration check passed
- [ ] S5.G5 Owner go-ahead, verified backup, `develop` merged into `main`, tag `v1.3.0`, release notes, docs and `SKILLS.md` updated, pushed

- [ ] S5.S1 Sprint standards (tests, security check, backup check, docs, 10 to 20% buffer)

### Backend, Sprint 5

- [ ] B21.1 Branch access requests and approvals (reason, destination Branch Admin or Super Admin, expiry or revoke, switch log)
- [ ] B22.1 Multi-role assignment by Super Admin, and a permissions review
- [ ] B22.2 Role switching: the selected role's permissions and dashboard only; each switch logged
- [ ] B23.1 Price history, the "Manage prices" permission, and the below-cost warning
- [ ] B24.1 User activity (track record) and stock movement history endpoints
- [ ] B25.1 Security review, performance check, tests, documentation and buffer
- [ ] B25.2 Phase 1 acceptance criteria checked (Backend section 13), release `v1.3.0`

### Frontend, Sprint 5

- [ ] F21.1 Branch access request and approval screens
- [ ] F22.1 Role assignment screen
- [ ] F22.2 Role switcher in the top bar; switching changes the whole view (menu, home dashboard, screens) to the selected role
- [ ] F23.1 Price history, manage prices, and below-cost warning display
- [ ] F24.1 User activity and stock movement history screens
- [ ] F25.1 Accessibility review, UI test pass, documentation
- [ ] F25.2 Phase 1 acceptance criteria checked (Frontend section 10), release `v1.3.0`

### DevOps, Sprint 5

- [ ] O5.1 Infrastructure security review
- [ ] O5.2 Restore test repeated
- [ ] O5.3 Performance check (search and product list within about 2 seconds)
- [ ] O5.4 Verified backup, deploy, smoke tests, deployment log entry

## PHASE 2

## SPRINT 6 (Days 26 to 30): Selling, part 1: price lists, branch overrides, discounts, receipts, customer details. Release: `v2.1.0`.

Branches: `sprint/6-selling-1` in both repos. Tag at end: `v2.1.0` on `main` in both repos.

### Git steps for Sprint 6 _(Applied in the end-of-day cycle (owner, 2026-11-23))_

- [ ] S6.G1 Backend: create `sprint/6-selling-1` from `develop`, push
- [ ] S6.G2 Frontend: create `sprint/6-selling-1` from `develop`, push
- [ ] S6.G3 Both repos: all Sprint 6 steps merged by pull request, one commit per step
- [ ] S6.G4 Both repos: sprint branch merged into `develop`, staging integration check passed
- [ ] S6.G5 Owner go-ahead, verified backup, `develop` merged into `main`, tag `v2.1.0`, release notes, docs and `SKILLS.md` updated, pushed

- [ ] S6.S1 Sprint standards (tests, security check, backup check, docs, 10 to 20% buffer)

### Backend, Sprint 6

- [ ] B26.1 Price lists
- [ ] B27.1 Branch price override
- [ ] B28.1 Discounts with permission, mandatory reason and recorded limit
- [ ] B29.1 Receipt data (reference, branch, staff, items, prices, total, payment method, time, warranty end date where applicable). Tax display waits for the accountant's answer
- [ ] B30.1 Customer details (required for warranty-bearing items)
- [ ] B30.2 Tests and release `v2.1.0`

### Frontend, Sprint 6

- [ ] F26.1 Price list screens
- [ ] F27.1 Branch price override screens
- [ ] F28.1 Discount entry in the sell screen
- [ ] F29.1 Receipt view (print and share)
- [ ] F30.1 Customer details in the sell screen
- [ ] F30.2 Tests and release `v2.1.0`

### DevOps, Sprint 6

- [ ] O6.1 Receipt print and share checked on real phones and a printer
- [ ] O6.2 Verified backup, deploy, smoke tests, deployment log entry

## SPRINT 7 (Days 31 to 35): Selling, part 2: split payments, daily close, returns and refunds, sales history, role dashboards, hardening. Release: `v2.2.0`.

Branches: `sprint/7-selling-2` in both repos. Tag at end: `v2.2.0` on `main` in both repos.

### Git steps for Sprint 7 _(Applied in the end-of-day cycle (owner, 2026-11-23))_

- [ ] S7.G1 Backend: create `sprint/7-selling-2` from `develop`, push
- [ ] S7.G2 Frontend: create `sprint/7-selling-2` from `develop`, push
- [ ] S7.G3 Both repos: all Sprint 7 steps merged by pull request, one commit per step
- [ ] S7.G4 Both repos: sprint branch merged into `develop`, staging integration check passed
- [ ] S7.G5 Owner go-ahead, verified backup, `develop` merged into `main`, tag `v2.2.0`, release notes, docs and `SKILLS.md` updated, pushed

- [ ] S7.S1 Sprint standards (tests, security check, backup check, docs, 10 to 20% buffer)

### Backend, Sprint 7

- [ ] B31.1 Split payments across methods
- [ ] B32.1 Daily close (cash-up), variances logged
- [ ] B33.1 Returns and refunds through reversals
- [ ] B34.1 Sales history filters (branch, staff, date, item, payment method) and role dashboard data
- [ ] B35.1 Hardening and release `v2.2.0`

### Frontend, Sprint 7

- [ ] F31.1 Split payment entry
- [ ] F32.1 Daily close screen
- [ ] F33.1 Returns and refunds screens
- [ ] F34.1 Sales history filters and role dashboards
- [ ] F35.1 Polish and release `v2.2.0`

### DevOps, Sprint 7

- [ ] O7.1 Concurrency and load check for simultaneous sales
- [ ] O7.2 Verified backup, deploy, smoke tests, deployment log entry

## SPRINT 8 (Days 36 to 40): Reports and exports. Release: `v2.3.0`.

Branches: `sprint/8-reports` in both repos. Tag at end: `v2.3.0` on `main` in both repos.

### Git steps for Sprint 8 _(Applied in the end-of-day cycle (owner, 2026-11-23))_

- [ ] S8.G1 Backend: create `sprint/8-reports` from `develop`, push
- [ ] S8.G2 Frontend: create `sprint/8-reports` from `develop`, push
- [ ] S8.G3 Both repos: all Sprint 8 steps merged by pull request, one commit per step
- [ ] S8.G4 Both repos: sprint branch merged into `develop`, staging integration check passed
- [ ] S8.G5 Owner go-ahead, verified backup, `develop` merged into `main`, tag `v2.3.0`, release notes, docs and `SKILLS.md` updated, pushed

- [ ] S8.S1 Sprint standards (tests, security check, backup check, docs, 10 to 20% buffer)

### Backend, Sprint 8

- [ ] B36.1 Sales reports (by period, branch, staff, product, payment method)
- [ ] B37.1 Stock balance, low stock and ageing reports
- [ ] B38.1 Receipt, supplier, transfer and shortfall reports
- [ ] B39.1 Adjustment and reversal history, stock valuation and margin (authorised roles only)
- [ ] B40.1 Audited CSV exports (products, stock balances, ledger history) and release `v2.3.0`

### Frontend, Sprint 8

- [ ] F36.1 Sales reports
- [ ] F37.1 Stock reports
- [ ] F38.1 Receipt, supplier, transfer and shortfall reports
- [ ] F39.1 Adjustment and reversal history, stock valuation and margin
- [ ] F40.1 Export buttons and release `v2.3.0`

### DevOps, Sprint 8

- [ ] O8.1 Report and CSV export run times and timeouts checked
- [ ] O8.2 Verified backup, deploy, smoke tests, deployment log entry

## SPRINT 9 (Days 41 to 45): Website API, inspection and grading per receipt line, supplier records, hardening. Release: `v2.4.0` (Phase 2 complete).

Branches: `sprint/9-phase2-complete` in both repos. Tag at end: `v2.4.0` on `main` in both repos.

### Git steps for Sprint 9 _(Applied in the end-of-day cycle (owner, 2026-11-23))_

- [ ] S9.G1 Backend: create `sprint/9-phase2-complete` from `develop`, push
- [ ] S9.G2 Frontend: create `sprint/9-phase2-complete` from `develop`, push
- [ ] S9.G3 Both repos: all Sprint 9 steps merged by pull request, one commit per step
- [ ] S9.G4 Both repos: sprint branch merged into `develop`, staging integration check passed
- [ ] S9.G5 Owner go-ahead, verified backup, `develop` merged into `main`, tag `v2.4.0`, release notes, docs and `SKILLS.md` updated, pushed

- [ ] S9.S1 Sprint standards (tests, security check, backup check, docs, 10 to 20% buffer)

### Backend, Sprint 9

- [ ] B41.1 Read-only website API: search and product detail
- [ ] B42.1 Availability by branch, API keys (stored hashed) and rate limits; no cost, customer or sales data exposed
- [ ] B43.1 Inspection and grading per receipt line (grade, test results, condition notes, photos)
- [ ] B44.1 Supplier records (name, contacts, terms, invoice and delivery note attachments)
- [ ] B45.1 Security review, buffer, Phase 2 acceptance criteria checked (Backend section 13), release `v2.4.0`

### Frontend, Sprint 9

- [ ] F41.1 API key management screen
- [ ] F42.1 Inspection and grading on the receiving screen
- [ ] F44.1 Supplier screens
- [ ] F45.1 Polish, final review, Phase 2 acceptance criteria checked (Frontend section 10), release `v2.4.0`

### DevOps, Sprint 9

- [ ] O9.1 Website API exposure checks (key storage, rate limits, CORS, no costs or customer data)
- [ ] O9.2 Final restore test with recovery time
- [ ] O9.3 Runbook reviewed
- [ ] O9.4 Owner go-ahead, verified backup, deploy, smoke tests, deployment log entry
- [ ] O9.5 Infrastructure notes for POS integration (a later update, not scheduled)

## DECISION LOG (working copy)

| Date | Decision | By |
|---|---|---|
| 2026-11-23 | No git workflow DURING a day: no branches, PRs or worktrees while building. Git runs only in /sync, the END-OF-DAY CYCLE, /emergency-push, or when the owner says "push". TASKS 0.1 steps 2-3, the git parts of 0.5, section 1, the G and S*.G steps, and SKILLS rule 15 apply there. They are marked "Applied in the end-of-day cycle (owner, 2026-11-23)" and are not deleted. Everything else stays in force: scope, quality, testing, security, honesty, gates, stock/ledger/audit/permission rules, accessibility, and "done only with evidence". | Owner |
| 2026-11-23 | B1.1 permission table (eqp4l-backend/docs/design/PERMISSION_TABLE.md) approved. | Owner |
| 2026-11-23 | B1.2 ERD (eqp4l-backend/docs/design/ERD.md) approved, including new tables idempotency_keys and dispatch_resolutions. | Owner |
| 2026-11-23 | OQ-4 to OQ-19: proposed answers approved as written. | Owner |
| 2026-11-23 | Frontend supporting packages approved: @vitejs/plugin-react, @tailwindcss/vite, jsdom, @eslint/js, typescript-eslint, eslint-plugin-react-hooks, globals, @types/react, @types/react-dom, @types/node. eslint 9.39.5 (deprecated) accepted until eslint-plugin-jsx-a11y supports ESLint 10. | Owner |
| 2026-11-23 | GAP-M10 / OQ-3: keep local zip snapshots for the whole project; database backup retention decided when hosting (O1.1) is chosen. | Owner |
| 2026-11-23 | FIX-4 approved: Idempotency-Key on every state-changing request (not only the 3 stock POSTs). Contract becomes v0.1.1. | Owner |
| 2026-11-23 | FIX-5 approved: snake_case status codes in the database and API, mapped 1:1 to the SKILLS status words shown on screens; account status 'Pending activation' (pending_activation) added. Contract v0.1.1. | Owner |
| 2026-11-23 | OQ-20 approved: Super Admin and Warehouse Admin can add, rename and deactivate brands (seeded list; endpoints in v0.1.1); image limit 5 MB, JPEG/PNG/WebP; Discontinued is final (no re-activation); dashboard shell fields as in the contract. | Owner |
| 2026-11-23 | Contract v0.1.1 also: A) GET /working-branch/ limited to FS and SA per permission table row 10; B) cost fields split into SA/WA-only schema variants so Item and StockBalance served to BA/FS carry no average_cost | Owner |
| 2026-11-23 | OQ-21 approved: an item can be activated without a selling price, but cannot be sold until a price exists; only Super Admin or a 'Manage prices' holder may send selling_price. | Owner |
| 2026-11-23 | OQ-22 approved: an account created (or reset) by a Super Admin starts as pending_activation and becomes active after the user's first password change; pending_activation is set only by the system, never via the status endpoint. | Owner |
| 2026-11-23 | Brands: a deactivated brand can be reactivated (SA or WA) and cannot be chosen for new items (400). | Owner |
| 2026-11-24 | OQ-23 approved: add permission and menu codes for Sell, Activity, Find and Receive to the contract with B3.4 (dashboard shell), so Super Admin Home opens them from server data. | Owner |
| 2026-11-24 | Contract v0.1.2 approved: a generic `conflict` error code (409) used for duplicate stock posts instead of idempotency_conflict, and the 429 response documented on /auth/password/. Publish at the start of Day 3; the frontend re-syncs. | Owner |
| 2026-11-24 | Super Admin and branches: a Super Admin is never asked to pick a branch at login. Super Admin works across ALL branches: lists and dashboard default to all branches, with an optional branch filter to view one branch, and every action available to them can be performed on any branch (actions on a record use that record's location, OQ-12). /me exposes `must_pick_branch` (true only when the user's role requires a working branch and none is chosen; always false for Super Admin). | Owner |
| 2026-11-24 | Contract v0.1.2 also approved: /me `home_links` (Sell, Activity, Find, Receive Home tiles, separate from the max-5 menu) and /me `can_assign_multiple_roles` (true only for Super Admin). | Owner |
| 2026-11-24 | OQ-26 decided: (1) Deactivated is final (suspend for temporary cases). (2) Last-Super-Admin guard: the system must always keep at least one active Super Admin; removing the SA role from, suspending or deactivating the last active SA is refused. (3) A Branch Admin's user list includes users whose permanent branch is theirs AND Front Staff currently working at their branch. (4) Password reset is refused for a deactivated user. | Owner |
| 2026-11-24 | OQ-25 (backend) decided: Warehouse Admin and Branch Admin open the Activity log from a Home tile (home_links), showing only their own location's activity (OQ-5). | Owner |
| 2026-11-24 | FIX-34 kept: Sentry uses sentry-sdk 3.0.0 `data_collection` (user_info false, stack_frame_variables false, cookies off, http_bodies []) because include_local_variables/send_default_pii do not exist in 3.0.0. | Owner |
| 2026-11-24 | Approved for the next contract version: /me `all_branches` (true when the user works across all branches, e.g. Super Admin), so the frontend stops inferring it. | Owner |
| 2026-11-24 | Contract v0.3.0 approved: read-only /stock/movements/; `duplicate_sku` warning removed (SKU clash = 409 conflict on sku); key-spec lists in inventory/catalog.py confirmed (OQ-27); 400 on list-filter operations; StockBalance `reorder_level` + server-computed `low_stock` (available at or below the level); `condition` filter on items; PATCH key_specs replaces the whole object; selling-price permission is `prices.manage` in /me. | Owner |
| 2026-11-24 | OQ-30 resolved (owner): by-id dispatch read and receive out of scope are 404, same as a missing id (contract v0.3.2); EXIF kept (not stripped); cost recheck found no gap, guard tests added. | owner |
| 2026-11-24 | OQ-31..33 approved (owner, relayed by the orchestrator): contract 0.4.0 (sales, item imports) as built; OQ-32 as built; OQ-33 fixed payment codes, customer name and phone deferred to Sprint 3; contract 0.4.1 adds SA-only `/costed-sales/` (new permission table row 48). | Owner |
| 2026-11-24 | FQ-11 answered (owner): contract 0.4.2, additive: `sales.cancel` and `items.import` in `ActionPermission`; Sales entry in `/me` menu for FS and in `home_links` for SA and BA (their menus are full at 5); permission table row 49. | Owner |
| 2026-11-24 | Daily branch choice (owner): a login drops any old session branch; Front Staff pick on the first login of the Africa/Accra day, later logins that day restore the first branch chosen that day (earliest switch-log row since local midnight, if still an active branch); a new day shows the picker. SA starts with no branch; BA and WA unchanged. No migration, no contract change. Test: tests/test_working_branch.py. | Owner |
| 2026-11-24 | Contract v0.3.1 approved (owner): `GET /dispatches/` documents 400 and 403 `wrong_branch`; dispatch stays WA and SA (table row 28); OQ-29 approved as proposed (reject stores received = sent, accepted 0; approve_partial without shortfall allowed; supplier name column 200). | owner |
| 2026-11-24 | Contract 0.5.0 approved and published (Day 7, additive): Dashboard gains low_stock_count, low_stock, recent_activity; GET /activity-log/; GET /shortfalls/; POST /shortfalls/{id}/resolve/ (id = dispatch line id; mandatory note; quantity up to the remaining shortfall; double resolution 409); new action shortfalls.resolve (SA, WA, BA; table rows 33 to 35). Resolver scope: WA the sender warehouse, BA the destination branch, SA both; out of scope is 404. Self-resolution allowed and flagged (OQ-9c). | Owner |
| 2026-11-24 | FQ-16 answered (owner): contract 0.5.2 (text only): `/auth/me/` `home_links` get an Activity tile (`/activity`, `activity.view`) and a Shortfalls tile (`/shortfalls`, `shortfalls.resolve`) for SA, WA, BA; FS none; no duplicates; menus stay at most 5. | Owner |

## DEFERRALS

- Barcodes and Code 128 labels, scanning, per-piece records and serial numbers, manufacturer barcode field and barcode/serial search, per-piece warranty and repair tracking, POS integration (tills, receipt printers, scanners), label printer and scanner hardware, bundles, stocktake workflow, email and SMS notifications, offline mode, lead capture and AI agent integration (not scheduled; can start after the website API in Sprint 9).

## OPEN QUESTIONS

Add a line here whenever a rule is missing, unclear or contradicted (rule 0.2). Critical and high gaps are tracked in [PROJECT_GAPS_AND_ACTIONS.md](PROJECT_GAPS_AND_ACTIONS.md).

| Ref | Question | Raised by | Answer | Answered by |
|---|---|---|---|---|
| OQ-1 | Development gate (rule 0.7): has the owner authorised development? | Doc sync 2026-11-18 | Yes, from Sprint 1 | Owner, 2026-11-18 |
| OQ-2 | Hosting provider, database host, object storage and domain names (O1.1) | DevOps doc | Open | |
| OQ-3 | Backup and log retention periods | DevOps doc | Decided (owner, 2026-11-23): local zips kept for whole project; DB retention set with hosting | |
| OQ-4 | IDs are immutable: if a USR- user is later made Super Admin (or an SA- user loses the role), what happens to the login ID? Proposed: ID never changes; SA- is only issued to accounts created as Super Admin. | backend-dev, B1.1 (PERMISSION_TABLE s4.1), 2026-11-23 | Approved (owner, 2026-11-23) | |
| OQ-5 | Who besides Super Admin may see the user list, session history and the activity log (FE 4.13 gives no role list)? Proposed: SA all; BA own branch activity; WA warehouse activity; FS none. | backend-dev, B1.1 rows 9, 41, 2026-11-23 | Approved (owner, 2026-11-23) | |
| OQ-6 | Who may run the CSV import of items and opening quantities? Proposed: SA and Warehouse Admin only. | backend-dev, B1.1 row 19, 2026-11-23 | Approved (owner, 2026-11-23) | |
| OQ-7 | Who may create, edit and discontinue items, set bin labels and reorder levels? Docs say WA manages items and SA/WA set reorder levels (C13). Proposed: SA and WA only for all three; BA and FS view only. | backend-dev, B1.1 rows 15, 17, 18, 2026-11-23 | Approved (owner, 2026-11-23) | |
| OQ-8 | What does a Warehouse Admin see of branch stock (Stock screen and dashboard 'stock per branch')? Proposed: warehouse stock in full; per-branch quantities only (no cost); BA and FS never see another branch's full stock. | backend-dev, B1.1 row 21, 2026-11-23 | Approved (owner, 2026-11-23) | |
| OQ-9 | Shortfall resolution: (a) may Front Staff view open shortfalls (read only)? (b) for a warehouse-to-branch dispatch, which locations count as 'allowed to act in': sender warehouse (WA), destination branch (BA), SA both? (c) may the user who recorded the shortfall also resolve it (non-SA)? Proposed: (a) no, (b) as stated, (c) yes for admin roles because resolution is not an approval request, but flagged in audit when same person. | backend-dev, B1.1 rows 33-35, 2026-11-23 | Approved (owner, 2026-11-23) | |
| OQ-10 | Can Front Staff list all sales of the branch or only their own? Proposed: all sales of the active branch (FE 4.10 says 'sales for the branch'). | backend-dev, B1.1 row 38, 2026-11-23 | Approved (owner, 2026-11-23) | |
| OQ-11 | Per-person permissions: which roles may hold 'Manage prices' and 'Discount'? Is the Discount grant stored from the MVP (no effect until Sprint 6)? Proposed: any role may hold either; Discount flag stored now, unused until Sprint 6. | backend-dev, B1.1 s3, 2026-11-23 | Approved (owner, 2026-11-23) | |
| OQ-12 | Does a Super Admin pick a working branch (so their sales and receipts record a branch), or is the branch taken from the record being acted on? Proposed: SA may optionally pick a context branch; actions on a record use that record's location. | backend-dev, B1.1 row 10, 2026-11-23 | Approved (owner, 2026-11-23) | |
| OQ-13 | Login rate limit numbers, lockout duration, password minimum length and one-time password expiry are not given. Proposed: 5 failed attempts per login ID and IP per 15 minutes, then a 15-minute wait; 10-character minimum; one-time password valid 72 hours. | backend-dev, B1.8 / B2 auth, 2026-11-23 | Approved (owner, 2026-11-23) | |
| OQ-14 | What is the difference between 'suspend' and 'deactivate' for a user, and are active sessions ended immediately? Proposed: suspend = temporary, reversible, sessions ended; deactivate = permanent leaving, sessions ended, history kept. | backend-dev, B1.1 row 4, 2026-11-23 | Approved (owner, 2026-11-23) | |
| OQ-15 | Can a dispatch be cancelled or amended after it is created, before the branch receives it? Docs are silent. Proposed: no in the MVP; reserved stock is released only through the resolution paths. | backend-dev, B1.1 row 32, 2026-11-23 | Approved (owner, 2026-11-23) | |
| OQ-16 | Average cost (ERD): (a) one average per SKU across all locations, or per location? (b) stored to 2 decimals or more internally (money rule says 2 dp)? (c) copy the average cost onto each sale line for later margin reports? Proposed: (a) one per SKU, (b) 4 internal decimals, 2 dp shown, (c) yes. | backend-dev, B1.2 (ERD item_costs, sale_lines), 2026-11-23 | Approved (owner, 2026-11-23) | |
| OQ-17 | Dispatch statuses: SPEC s5.4 lists Draft, dispatched, in transit, partially received, completed, rejected, under investigation. Proposed MVP set: in_transit, completed, partially_received, rejected, with 'open discrepancy' derived; draft and under investigation unused until Sprint 4. Also: may physical received exceed sent (over-delivery)? Proposed: no, reject the entry. | backend-dev, B1.2 (ERD dispatches), 2026-11-23 | Approved (owner, 2026-11-23) | |
| OQ-18 | Public reference formats and SKU generation (SKILLS 'Keys: open'). Proposed: GRN-000001, TRF-000001, SAL-000001, RES-000001 (sequence per type); SKU system-generated SKU-000001 or imported unchanged. | backend-dev, B1.2 (ERD conventions), 2026-11-23 | Approved (owner, 2026-11-23) | |
| OQ-19 | Item sub-type lists and MVP key specs: BE lists part and accessory types, but laptop sub-types are not stated, and MVP key specs have no field list. Proposed: laptop sub-type = segment list in BE 3.3; parts and accessories use the type lists in BE 3.4 and 3.5; MVP key specs stored as validated JSON until Sprint 3. | backend-dev, B1.2 (ERD categories, items), 2026-11-23 | Approved (owner, 2026-11-23) | |
| OQ-20 | Item API details not in the docs: (a) who manages the brand list (contract has GET only), (b) maximum image size, (c) may a Discontinued item be re-activated, (d) fields of the Sprint 1 dashboard shell. Proposed: (a) SA and WA add brands (POST /brands/ to be added to the contract after approval), (b) 5 MB, (c) no, (d) as in the Dashboard schema of docs/api/openapi.yaml. | backend-dev, B1.3, 2026-11-23 | Approved as proposed (owner, 2026-11-23); in contract v0.1.1 | |
| OQ-21 | Selling price on item create/edit: contract lets only SA or a Manage prices holder send `selling_price` (row 16); WA without the grant gets 403 on that field. Confirm, and say if an item may be activated without a price. | backend-dev, B1.3, 2026-11-23 | Approved (owner, 2026-11-23): confirmed; activation needs no price, sale blocked until a price exists; in contract v0.1.1 | |
| OQ-22 | FIX-5 added account status `pending_activation` but not its meaning. When does an account have it, and which targets may `POST /users/{id}/status/` accept? Proposed: a user created by SA is `pending_activation` until the first password change, then `active`; the status endpoint accepts `active`, `suspended`, `deactivated` only (as written in contract v0.1.1). | backend-dev, contract v0.1.1, 2026-11-23 | Approved (owner, 2026-11-23) | |
| OQ-24 | Client IP behind a proxy: the login and password rate limits key on `REMOTE_ADDR`/X-Forwarded-For handling; a trusted-proxy setting is needed once the host is known. | backend-dev, day-2 review finding 7, 2026-11-23 | BLOCKED by O1.1 (hosting) | |
| OQ-25 | Where do Warehouse Admin and Branch Admin open the Activity log (row 41)? Docs place it only on the Super Admin Home; BA's nav already has 5 items and WA has no Home tile list. Built: `activity.view` for SA, WA, BA; only SA gets the Activity Home tile. | backend-dev, B3 (contract v0.1.2), 2026-11-24 | Decided (owner, 2026-11-24) | |
| OQ-26 | User management edges not in the docs: (a) is Deactivated final (built: yes, only suspended can return to active, per OQ-14 "permanent")? (b) may a Super Admin remove their own Super Admin role or edit it away (built: allowed, no last-SA guard)? (c) BA "own branch" user list = users whose permanent location is that branch; Front Staff have none, so BA never sees FS (built literally per OQ-5). (d) reset password on a deactivated user is refused (409); `receive_stock` may be held only by Front Staff (table s3). | backend-dev, B3.3, 2026-11-24 | Decided (owner, 2026-11-24) | |
| OQ-27 | MVP key-spec field lists (OQ-19 gave no list): built Laptop (processor, ram_gb, storage_gb, storage_type required to activate; screen size, touchscreen, OS, keyboard layout, colour optional), Laptop Part (quality_type required; compatible models, colour), Accessory (connectivity, colour, compatibility notes), all in `inventory/catalog.py`. Please confirm or send the real lists. | backend-dev, B4.1, 2026-11-24 | Approved as built (owner, 2026-11-24) | Owner |
| OQ-28 | Contract says an exact duplicate SKU is a non-blocking `duplicate_sku` warning, but SKU is UNIQUE in the ERD. Built: a SKU clash (any case) is 409 `conflict` on field `sku`; only `duplicate_name_model` warnings are emitted. Also: no endpoint to READ the movement log exists in contract 0.2.0 (B4.3 builds the ledger and the stock service only). | backend-dev, B4.1/B4.3, 2026-11-24 | Approved (owner, 2026-11-24): SKU clash is 409 `conflict` on `sku`, `duplicate_sku` warning removed; read-only `/stock/movements/` added. Contract 0.3.0 | Owner |
| OQ-29 | Receiving edge cases the docs do not fix. Built: (a) `approve_partial` with no shortfall is accepted (status `partially_received`, no discrepancy); (b) a `reject` stores qty_received = qty_sent, qty_accepted 0, qty_rejected = qty_sent (goods arrived but refused; everything stays reserved at the sender); (c) `has_open_discrepancy` = any line with shortfall greater than the sum of its resolutions; (d) GRN supplier name column widened 150 to 200 to match the contract (migration warehouse 0002); (e) dispatch list contract 0.3.0 documents only 200/401 but BA/FS get 403 `wrong_branch` and a bad `status` is 400 (additive doc fix proposed for the next contract version); (f) SA also holds `dispatches.create` per table row 28 (WA and SA). | backend-dev, B5.1-B5.4, 2026-11-24 | Approved (owner, 2026-11-24) | Owner |
| OQ-30 | RESOLVED. Notes from the Day 5 review (no code): (a) `warehouse/services.py` creates a new ItemCost from the receipt cost alone and ignores stock already at other locations; re-check at the CSV opening-stock step. (b) A dispatch outside the caller's branch returns 403 `wrong_branch`, while a nonexistent id returns 404; the owner may prefer 404 for both. Day 5 review tests added (no bugs found): average restarts at the new cost after stock hits 0; same Idempotency-Key from two users gives two receipts with distinct operation_ids. | backend-dev, B5.6 review, 2026-11-24 | Resolved 2026-11-24 | Owner | Resolution: (a) cost recheck: no stock can exist without an ItemCost row today (only `create_receipt` adds stock, and it creates the cost row first; `seed_dev` creates the cost row with the item; dispatch only moves existing stock; `post_stock_changes` callers elsewhere are tests); guard tests added and a `shortcut:` comment sits at `warehouse/services.py` `_fold_average_cost`; the CSV opening-stock step must create or fold cost first. (b) owner: by-id dispatch reads and receipts out of scope return 404 like a missing id; contract 0.3.2; list unchanged. (c) EXIF: owner decided keep as is (not stripped); README Deploy notes updated. |

| OQ-31 | GATE G6-1 (contract): sales and item-import operations are NOT in contract 0.3.2, so Day 6 added them as an additive proposal, contract 0.4.0 (`/sales/`, `/sales/{id}/`, `/sales/{id}/cancel/`, `/item-imports/`; no published operation changed). Needs owner approval and a frontend contract sync. Also: sale payloads carry NO cost for any role. The brief wanted the sale-line cost snapshot at 2 dp in the API for SA; that needs a costed variant (for example `GET /costed-sales/`, SA only) and a permission table row ("see sale line cost": SA; WA has no sales access), because the table's cost rule is SA and WA and the existing contract tests only accept SA,WA variants. Recommend: add table row 48 and `/costed-sales/{id}/` in 0.4.1. The 4 dp snapshot is stored on every sale line. | backend-dev, B6.1, 2026-11-24 | Approved (owner, 2026-11-24, relayed by the orchestrator): contract 0.4.0 as built; cost gap fixed in contract 0.4.1 (`/costed-sales/`, SA only, table row 48) | Owner |
| OQ-32 | CSV import creates new items as Draft (no image, no required specs) and posts opening stock to them, although "only Active items can be received". Existing SKUs (any status except Discontinued) are reused unchanged and item columns on that row are ignored. Re-importing the same SKU at the same location ADDS stock again (no duplicate-opening-balance guard; a retry with the same Idempotency-Key is safe). Decide: allow stock on Draft items, and whether a second opening balance for one SKU and location should be refused. | backend-dev, B6.4, 2026-11-24 | Approved (owner, 2026-11-24, relayed by the orchestrator): keep as built | Owner |
| OQ-33 | Sales: (a) customer name and phone (required for warranty items per BE s6) have no column on `sales_sale`, so they need a migration and a rule for which items are warranty-bearing; not built. (b) The frontend needs the payment-method list; built as fixed codes cash, mobile_money, card in the contract enum, with no list endpoint. (c) Sale detail of another branch is 404 for BA and FS (OQ-30 style); a list `branch` filter for another branch is 403. | backend-dev, B6.1-B6.2, 2026-11-24 | Approved (owner, 2026-11-24, relayed by the orchestrator): fixed payment codes kept; customer name and phone deferred to Sprint 3 | Owner |
| OQ-34 | CSV formula injection: a future CSV export (B40.1) must neutralise cells that start with `=`, `+`, `-` or `@` (for example by prefixing a quote), because item names, SKUs and notes come from users and imports. The import itself stores text as given (`inventory/imports.py` `_lookup`). Decide the exact rule before B40.1. | backend-dev, Day 6 review, 2026-11-24 | Open | Owner |
| OQ-35 | Upload size: the import checks 2 MB after the body is read (`inventory/imports.py` `_parse`); the real limit on request bodies must also be set by the host or proxy (see README Deploy notes). Add to the O1.1 hosting checklist. | backend-dev, Day 6 review, 2026-11-24 | Open (blocked by O1.1) | Owner |

## FIX LOG

| Ref | What was wrong or changed | Repo | Branch | Test added | Merged | Released in |
|---|---|---|---|---|---|---|
| FIX-1 | ERD: `idempotency_keys` UNIQUE(actor_id, scope, key), looked up by all three; same key with another body returns 409 `idempotency_conflict`. Required B4.3 test: user B replaying user A's key never gets A's stored body. | backend | n/a (no git by day) | Future test in ERD s4 and B4.3 | | |
| FIX-2 | ERD: `average_cost` numeric(14,4) per SKU (OQ-16); `sale_lines.unit_cost_snapshot` numeric(14,4), SA/WA only; API 2 dp. Required test: snapshot stored at 4 dp, API 2 dp, absent for BA/FS (Sprint 2 sales and B4.3). | backend | n/a | Future test in ERD s4 | | |
| FIX-3 | OQ-3..OQ-19 folded into PERMISSION_TABLE.md cells and ERD.md; stale "awaiting approval"/OPEN text removed (OQ-20, OQ-21 stay open); REQUIREMENTS_DIGEST.md:44 no longer "draft". Contract mismatch reported: `GET /working-branch/` says any logged-in user but cites row 10 (FS, SA). | backend | n/a | tests/test_permission_table_contract.py | | |
| FIX-4 | Done (contract v0.1.1): Idempotency-Key on every state-changing operation except login, logout, password change. | backend | n/a | tests/test_openapi_contract.py | | |
| FIX-5 | Done (contract v0.1.1, ERD.md): snake_case status codes mapped 1:1 to SKILLS words; `pending_activation` added (meaning: OQ-22 open). | backend | n/a | tests/test_openapi_contract.py | | |
| FIX-6 | `.dockerignore`: backups/, .env.*, !.env.example, htmlcov/ (.env kept). Prod image verified to have no /app/backups. | backend | n/a | Manual image check | | |
| FIX-7 | Scripts invoked as `bash scripts/...` (Dockerfile CMD, dev.ps1, PR template, CI, compose); CI step builds the prod image and checks /health/ with DEBUG off. Local equivalent run: 200. | backend | n/a | CI step | | |
| FIX-8 | `SECURE_REDIRECT_EXEMPT = [r"^health/$"]`; http /health/ is 200 with DEBUG off (other paths still 301). | backend | n/a | tests/test_settings.py | | |
| FIX-9 | ERD: `import_batches` table is the `source_id` of `csv_import` ledger rows (source_line_id = CSV row). Required stock-service test: same import row posted twice writes one ledger row (B4.3). | backend | n/a | Future test in ERD s4 and B4.3 | | |
| FIX-10 | Tests: no cost/unit_cost/average_cost property reachable by BA/FS operations; generated spectacular paths are a subset of the contract. Known contract gap: `Item` and `StockBalance` are shared with BA/FS and carry `average_cost` (documented SA/WA only); resolved in contract v0.1.1 (cost variants for SA/WA only); the allow-list is removed and the test is strict. `GET /working-branch/` mismatch (FIX-3) also resolved: FS and SA only. | backend | n/a | tests/test_contract_security.py | | |
| FIX-11 | Test: DEBUG defaults to False when DJANGO_DEBUG is unset. | backend | n/a | tests/test_settings.py | | |
| FIX-12 | Compose web port published as "127.0.0.1:8000:8000". | backend | n/a | Manual (docker compose up) | | |
| FIX-13 | bandit scanned only config/; now scans the whole project (tests, docs, backups, venv excluded). | backend | n/a | tests/test_check_config.py | | |
| FIX-14 | Coverage gate measured only config/; now --cov=. with tests, migrations, manage.py, wsgi/asgi omitted. | backend | n/a | tests/test_check_config.py | | |
| FIX-15 | Production start ran migrate without a backup (rule 0.6); auto-migrate is now opt-in via AUTO_MIGRATE=True (compose and CI only). | backend | n/a | tests/test_check_config.py | | |
| FIX-16 | SPECTACULAR VERSION 0.1.0 vs contract 0.1.1; set to 0.1.1 and tested equal. | backend | n/a | tests/test_check_config.py | | |
| FIX-17 | check.sh comment used the non-bash invocation; corrected. | backend | n/a | n/a | | |
| FIX-18 | `assign_roles` now requires `users.manage` for an actor and refuses (403) when existing + wanted roles exceed one for a non-Super Admin. | backend | n/a | tests/test_permissions.py (guard test: `require_action` already refused; union rule added as defence) | | |
| FIX-19 | Login rate-limit race: count-then-log serialised per (login ID, IP) with `pg_advisory_xact_lock`. | backend | n/a | tests/test_auth.py (10 concurrent: 5x 401, 5x 429; failed first) | | |
| FIX-20 | Append-only tests cover all 6 tables x UPDATE, DELETE, TRUNCATE; TRUNCATE privilege asserted revoked by `lock_append_only_tables`. | backend | n/a | tests/test_append_only.py (guard test: all already held) | | |
| FIX-21 | Stock service: a duplicate source-line post is 409 `idempotency_conflict` (nearest existing contract code; no generic conflict code exists); every running balance step is validated (409 `insufficient_stock`), no IntegrityError. | backend | n/a | tests/test_stock_service.py | | |
| FIX-22 | Session fixation: login replaces a planted anonymous session key. | backend | n/a | tests/test_auth.py (guard test) | | |
| FIX-23 | `/auth/password/`: wrong current password limited to 5 per 15 min per user, then 429 `rate_limited` + Retry-After; every try logged (login_log + audit `password_change_failed`, no password). Contract gap: `/auth/password/` lacks a 429 response and `TooManyRequests` says "Login rate limit". | backend | n/a | tests/test_auth.py | | |
| FIX-24 | (number kept for the brief's finding 7) Trusted-proxy client IP deferred, see OQ-24 (blocked by O1.1). | backend | n/a | n/a | | |
| FIX-25 | TRUNCATE trigger on `accounts_loginidsequence` (new migration accounts 0005; 0004 already applied to the dev DB); ERD.md table-name note added; test conftest flush also disables it. | backend | n/a | tests/test_ids.py | | |
| FIX-26 | Comments fixed: `.env.example` dev seed users (active, no forced change, local only); `roles/models.py`, `sales/models.py` seeding is post_migrate in `config/reference_data.py`. | backend | n/a | n/a | | |
| FIX-27 | Contract v0.1.2 (owner-approved 2026-11-24): generic `conflict` 409 code; stock service duplicate post now answers `conflict` (was `idempotency_conflict`, FIX-21); 429 on /auth/password/; OQ-23 codes and `/me` `home_links`, `can_assign_multiple_roles`, `must_pick_branch`; SA `?branch=` view filter; dashboard 403 for FS (row 40). | backend | n/a | tests/test_stock_service.py, tests/test_openapi_contract.py, tests/test_b3_matrix.py | | |
| FIX-28 | OQ-26 last-Super-Admin guard: removing the SA role from, suspending or deactivating the last active SA (also the actor) is 409 `conflict` with a plain message; active SA rows locked. | backend | n/a | tests/test_users_api.py | | |
| FIX-29 | OQ-26 Branch Admin user list and detail: own permanent-branch users plus Front Staff whose live session working branch is theirs; nobody else (404). | backend | n/a | tests/test_users_api.py | | |
| FIX-30 | OQ-25 home_links: Warehouse Admin and Branch Admin get an Activity tile (activity.view, own location). PERMISSION_TABLE rows 4, 9, 45 updated. | backend | n/a | tests/test_permissions.py | | |
| FIX-31 | OQ-26 deactivated is final and reset refused for deactivated: confirmed covered. No contract shape change (v0.1.2 kept). | backend | n/a | tests/test_users_api.py (existing) | | |

## DEPLOYMENT LOG

| Version | Environment | Backup verified | Migrations run | Smoke tests passed | Rollback ready | Approved by owner |
|---|---|---|---|---|---|---|
| (first entry goes here) | | | | | | |
| FIX-32 | BLOCKER: Receive stock is Front Staff only (s3). Removing front_staff from a user revokes an active receive_stock grant in the same transaction (audit `permission_revoked`, reason "role change"); `effective_actions` adds dispatches.receive from the grant only when the active role is front_staff. | backend | n/a | tests/test_users_api.py | | |
| FIX-33 | BLOCKER: last-SA guard deadlock. Target plus all active Super Admin rows are locked in one query (order by pk, `select_for_update(of=("self",))`) before any other lock, in status and role-change paths. Threaded test: two SAs suspend each other, one 200 and one 409, one active SA left. (Guard test: the old code passed it by timing in one run; the ordering fix is by construction.) | backend | n/a | tests/test_users_api.py | | |
| FIX-34 | Sentry init no longer sends local variables or PII. The requested `include_local_variables=False, send_default_pii=False` raise `TypeError: Unknown option` in the pinned sentry-sdk 3.0.0 (would crash startup when a DSN is set), so `data_collection={user_info: False, stack_frame_variables: False, cookies: off, http_bodies: []}` is used. Test also runs a real init. | backend | n/a | tests/test_settings.py | | |
| FIX-35 | "Front Staff working at their branch" (BA user list) requires the user's active role to be front_staff (an SA+FS user with a context branch is not listed). Accepted shortcut: a stale session keeps its stored branch until it ends (up to SESSION_COOKIE_AGE); recorded in the code comment. | backend | n/a | tests/test_users_api.py | | |
| FIX-36 | Guard test for 409 "You cannot change your own status" with a second active SA present (the old test hit the last-SA message). | backend | n/a | tests/test_users_api.py | | |
| FIX-37 | Note, behaviour unchanged: the one-time password can be shown again to the SAME actor replaying the SAME Idempotency-Key (needed for network retries). Rotating SECRET_KEY invalidates such replays. Noted in docs/design/ERD.md (idempotency). | backend | n/a | n/a | | |
| FIX-38 | End-of-day review: the idempotency body hash used the uploaded file's name, so the same key and name with another image replayed instead of 409. Now hashes the file content. | backend | n/a | tests/test_items_api.py::test_same_key_and_file_name_but_different_image_bytes_is_409 | | |
| FIX-39 | End-of-day review: two copies of one stock operation_id touching different items both posted (replay lookup ran after the balance locks). Now a `pg_advisory_xact_lock` on the operation_id is taken first; the second gets 409 `idempotency_conflict`. | backend | n/a | tests/test_stock_service.py::test_same_operation_id_on_different_items_posts_once | | |
| FIX-40 | End-of-day review: an image file written before a failed transaction stayed on disk. The file is now deleted when the item save or audit fails. | backend | n/a | tests/test_items_api.py::test_a_failed_upload_leaves_no_file_behind | | |
| FIX-41 | Documentation: README "Deploy notes" now gives the proxy body limit (~6 MB) for uploads, MEDIA_ROOT, and that EXIF is not stripped (owner decided 2026-11-24: keep as is). | backend | n/a | n/a | | |
| FIX-42 | Day 6 review: the CSV import folded ItemCost in file order while receipts lock by item id (deadlock risk). The fold now runs in `_commit`, sorted by item id, just before the stock is posted; a dry run takes no cost locks. | backend | n/a | tests/test_b6_review2.py::test_an_import_and_a_receipt_over_the_same_items_in_opposite_order_both_finish | | |
| FIX-43 | Day 6 review: the sale read the cost before its transaction, so the snapshot could be stale after a receipt. It is now read inside the transaction under `select_for_update`, in item order. | backend | n/a | tests/test_b6_review2.py::test_a_sale_waiting_for_a_cost_change_snapshots_the_new_cost | | |
| FIX-44 | Day 6 review: repeated CSV header names and rows with extra cells were silently accepted. Repeated names are a 400 on `file`; extra cells are a row error. | backend | n/a | tests/test_b6_review2.py (two tests) | | |
| FIX-45 | Day 7 review: dashboard low stock for a WA or BA with no location was unfiltered. It is now empty (count 0). | backend | n/a | tests/test_b7.py::test_fix45_admins_without_a_location_never_see_unfiltered_low_stock | | |
| FIX-46 | Day 7 review: SA low stock included inactive locations. It now matches stock_per_location (active only). | backend | n/a | tests/test_b7.py::test_fix46_super_admin_low_stock_skips_inactive_locations | | |
| FIX-47 | Day 7 review: index on audit events (location, occurred_at) for the scoped activity log, new migration audit 0003. | backend | n/a | tests/test_b7.py::test_fix47_audit_events_have_a_location_time_index | | |
| FIX-48 | Day 7 review: activity log `date_from` after `date_to` is 400 on `date_to`. Contract text only, version 0.5.1. | backend | n/a | tests/test_b7.py::test_fix48_date_from_after_date_to_is_a_400_on_date_to | | |
| FIX-49 | Day 7 review decision (assistant recommendation, owner may overrule, 2026-11-24): a shortfall at a deactivated location can still be resolved, so stranded reserved stock can always be cleaned up. Documented by test, no code change. | backend | n/a | tests/test_b7.py::test_fix49_a_shortfall_at_a_deactivated_location_can_still_be_resolved | | |

## Step
<!-- Step code(s), e.g. B2.1, and the linked requirement sections -->

## What changed and why

## Checklist (TASKS rule 0.3: a step is not done until all pass)
- [ ] Code works; tests for this step exist and pass (happy, rejection, permission and failure paths)
- [ ] Single check command is green (paste the real output below)
- [ ] Every stock change goes through the one stock service (atomic, row-locked, ledger entry)
- [ ] Audit trail and stock ledger stay append-only (no update or delete paths)
- [ ] Permissions enforced on the server (role, active branch, approved access)
- [ ] No secrets in code or git; env vars only
- [ ] Cost price visible only to Super Admin and Warehouse Admin; cross-branch lookup shows branch name and quantity only
- [ ] Timestamps timezone-aware (Africa/Accra display); money is Decimal GHS 2 dp
- [ ] No applied migration edited; `makemigrations --check` is clean
- [ ] OpenAPI contract unchanged, or the contract-change rule (TASKS 0.2) was followed
- [ ] Docs, SKILLS.md (installs) and TASKS.md ticks updated in this PR

## Check output
```
(paste the real tail of `docker compose run --rm web bash scripts/check.sh`)
```

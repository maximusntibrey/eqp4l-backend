# Requirements Digest (B1.4)

Short version for day-to-day use. Full text wins on any difference. Refs: OVR = 1-Overview-and-Sprints, FE = 2-Frontend, BE = 3-Backend, SPEC = 6-Functional-Workflow-Specification, DEC = workspace CLAUDE.md decisions, TASKS = TASKS.md.

## Product
- Inventory and warehouse system for Payless4Laptops: one central warehouse plus branches; stock counted as quantity per SKU per location, no per-piece tracking (OVR 5, BE 14). Online only. GHS, Africa/Accra.
- Backend = Django REST + PostgreSQL. The OpenAPI contract is the only link to the frontend (OVR 3, TASKS 0.2).
- MVP = Sprints 1-2 (10 days), release `v1.0.0` (BE 12, 13).

## Roles and access (BE 2, OVR 1-2)
- Roles: Super Admin (SA-0001 IDs), Warehouse Admin, Branch Admin, Front Staff (USR-0001 IDs). IDs immutable, never reused. One role per user until Sprint 5; only SA assigns more.
- Front Staff pick any active branch after login, switches logged. BA and WA have one permanent location. Temporary access requests are Sprint 5.
- Every protected action checked on the server: role, active branch, approved access, per-person permissions (Receive stock, Manage prices, discount). SA grants them.
- Cross-branch lookup: any user sees other branches' quantity by branch name and quantity only. Cost price only for SA and WA (OVR 7).
- SA can self-approve (flagged in audit); nobody else can (OVR 3).
- Password: one-time password shown once on create or reset, forced change at first login (DEC C5).

## Stock rules (BE 3.8, SPEC 11, DEC)
- Per SKU per location: on_hand, reserved, quarantined. Available = on_hand - reserved. In transit is derived from open dispatch lines.
- Dispatch: sender reserved +q. Receipt of accepted a: sender reserved -a and on_hand -a, destination on_hand +a. Short or rejected quantity stays reserved as a discrepancy.
- Resolution (admin roles, note required): return = reserved -q; loss = reserved -q, on_hand -q; damage = reserved -q, on_hand -q at sender, destination quarantined +q.
- No negative stock. Every change through ONE stock service: atomic, row-locked, idempotent, one append-only ledger row per bucket change with a stable source reference and line ID (GAP-C02). Ledger and audit are append-only.

## MVP functions by day (BE 12)
- Day 1: permission table, ERD, contract, CI, check command, digest.
- Day 2: schema, user model and ID generator, login, sessions, rate limit, login log, permissions, seed (SA-0001, 3 branches, sample items and stock).
- Day 3: working-branch select and switch, branch API, user API (reset password, per-person permissions), dashboard shell.
- Day 4: item API (common fields, key specs, Draft/Active, one image), stock service, balances, stock query.
- Day 5: warehouse receipt (supplier name, lines, quantity, cost), dispatch (WA only), branch receiving with shortfall flag, waiting-at-branch queries.
- Day 6: sale API (price from price list, payment method, overselling blocked), sales list, Find with other branches' quantities, CSV import with opening stock and error report, cancel sale (SA, BA, reason, reversal).
- Day 7: dashboard and activity endpoints; shortfall resolution (return, loss, damage) with mandatory note.
- Days 8-10: end-to-end, permission and branch-isolation tests, performance and security check, backup and restore test, production release after owner go-ahead.

## Items and money (BE 3, DEC)
- Item: SKU (immutable once used), name, category (Laptop, Laptop Part, Accessory) and sub-type, brand, model, MPN, condition (New, Refurbished, Used), grade A/B/C, status Draft/Active/Discontinued. Only Active items move. No delete once used.
- Price list: one row per SKU, set by SA or "Manage prices", no negatives. Cost recorded at receipt, average cost, visible to SA and WA only. Optional reorder level per item per location (SA, WA, also via CSV). Optional bin label.
- Money: Decimal, 2 dp. Sales never edited; cancellation is a linked reversal. Statuses: Completed, Cancelled, Refunded, Exchanged.

## Quality gates (TASKS 0.3, SKILLS)
- Tests per step (happy, rejection, permission, failure); one check command green; docs and ticks updated; no secrets in git; migrations never edited after applied; ERD and permission table approved before any migration (B1.1, B1.2).
- Out of scope now: barcodes, per-piece records, POS, email/SMS, offline, stocktake, bundles (BE 14).

## Where things are
- Permission table (approved 2026-11-23): `docs/design/PERMISSION_TABLE.md`. ERD (approved 2026-11-23): `docs/design/ERD.md`. Open questions: TASKS "OPEN QUESTIONS" (OQ-4 to OQ-19 approved; OQ-20, OQ-21 open).
- Check command: `docker compose run --rm web bash scripts/check.sh`. Install register: SKILLS Appendix A.

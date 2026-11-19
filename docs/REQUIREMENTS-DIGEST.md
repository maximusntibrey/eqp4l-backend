# Requirements digest (B1.4)

A short summary of the backend requirements for Sprints 1 and 2. It adds, infers and resolves nothing. Where sources disagree, the point is under "Conflicts noticed". Sources are cited as: **BE** = `3-Backend-Requirements.md`, **OVR** = `1-Overview-and-Sprints.md`, **GAP** = `PROJECT_GAPS_AND_ACTIONS.md`, **SPEC** = `6-Functional-Workflow-Specification.md` (background per GAP-C04; s11.2 is binding for stock buckets and movements per GAP-C07; s11.1 and s11.3 are cited as background). All live in the `inventory/` folder outside this repo. If this digest and a source differ, the source wins (GAP-C04).

## 1. Roles and scope

- Four roles: Super Admin, Warehouse Admin, Branch Admin, Front Staff. One account per person. Only Super Admins assign more than one role. (BE s2; OVR s1 #2)
- Login IDs: `SA-0001` format for Super Admins, neutral `USR-0001` format for everyone else. Never changed, never reused. (BE s2; OVR s1 #2)
- Super Admin can do everything in every branch, plus manage accounts, roles, branches and prices. Actions are recorded under their own ID with the role and branch used. They may approve their own requests; each self-approval is flagged in the audit trail. Nobody else may approve their own request. (BE s2, s13; OVR s1 #3)
- Warehouse Admin: manages items, receives into the warehouse, dispatches to branches, sees cost. Branch Admin: runs a branch, receives, sells, cancels sales, no cost. Front Staff: sells, finds items, receives only with the per-person Receive stock permission, no cost. (OVR s2, s1 assumptions)
- Per-person permissions (Receive stock, Manage prices, discount) are granted by a Super Admin from the user edit screen until the Sprint 5 role screen. (OVR s1 #15; GAP-C06; BE Sprint 1 Day 3)
- Combined roles: a role switcher; the server returns the menu, dashboard and permissions of the selected role only and logs the switch. (BE s2; OVR s1 #12; GAP-C05) Scheduled for Sprint 5, so not in Sprints 1-2 (BE Sprint 5 Day 22).
- Account administration: create, edit, activate, deactivate, suspend, reset credentials; history is kept on deactivation. (BE s2)

## 2. Branch rules

- One central warehouse plus branches; each location holds its own balances. (BE s2)
- Front Staff may pick any active branch after login; the server scopes every request to it; each switch is logged. (BE s2; OVR s1 #1; GAP-C05)
- Other users have one permanent branch. Temporary access elsewhere needs a request with a reason, approved by the destination Branch Admin or a Super Admin. (BE s2) Scheduled for Sprint 5 (BE Sprint 5 Day 21).
- Warehouse-to-branch assignment is Warehouse Admin (and Super Admin) only. (BE s2)
- Every protected action is checked server-side against role, active branch and approved access. (BE s2, s11)

## 3. Stock buckets and ledger rules

- Stock is a quantity per SKU per location. No per-piece tracking now. (BE s3.1; OVR s1 #5)
- Per SKU and location: on hand, reserved, in transit, quarantined or damaged, and available (available = on hand minus reserved). (BE s3.8)
- Movements follow SPEC s11.2 (binding per GAP-C07, which summarises it as "dispatch: available → reserved/in transit; receipt credits approved quantity only"). SPEC s11.1 (background) defines only on hand, reserved and available (available = on hand minus reserved). SPEC s11.2 has no quarantined/damaged bucket. It uses "In-transit quantity" ("In-transit quantity resolved" on approval) without defining it, and s11.1 does not define it either, so whether in transit is a separate bucket is not stated. Dispatch decreases available and increases reserved at the sender; approval raises the destination's on hand by the accepted quantity. The five-bucket list above (including in transit and quarantined or damaged) comes from BE s3.8 only. Storage detail is decided in the ERD (B1.2). (SPEC s11.2 binding, s11.1 and s11.3 background; BE s3.8; GAP-C07)
- The stock ledger is append-only. Each row references its source transaction and carries location, item, quantity, user and time, plus a stable source reference and line ID so a unit reference can be added later. (BE s9, s14; GAP-C02)
- Balances cannot go negative. Receipts are never silently edited; corrections use a reversal or adjustment. Duplicate submissions are prevented; balances and ledger entries commit together. (BE s3.12, s4)
- Every stock change uses database transactions, row-level locking and idempotency keys. (BE s11)
- Opening balances load through a CSV import that writes ledger movements, never by editing balances. (BE s3.11)

## 4. Sprint 1-2 workflows

- Sprint 1: scope and permission table, data model and OpenAPI contract, repo/CI/check command, this digest (Day 1); schema, user model and ID generator, login, logout, hashing, sessions, rate limit, login log, permission checks, seed data (SA-0001, 3 branches, sample items with stock) (Day 2); working-branch selection and switching, branch API, user management API, dashboard shell (Day 3); item API (Draft or Active, one image upload), stock service and movement log, stock query API (Day 4); warehouse receipt API, dispatch API (Warehouse Admin only), branch receiving API with shortfall flagged, queries for what is waiting at each branch (Day 5). (BE s12)
- Sprint 2: sale API (blocks overselling) and branch sales list, find and search including other branches' quantities, CSV import with error report, cancel sale (Super Admin and Branch Admin, reason required, reversal entry) (Day 6); dashboard and activity endpoints, basic dispatch shortfall resolution (return to sender, confirm loss, record damage) with a mandatory note (Day 7); end-to-end, permission and isolation tests (Day 8); performance, security, backup and restore checks (Day 9); production deployment after owner go-ahead, `v1.0.0` (Day 10). (BE s12; OVR s4)
- Receiving: the destination enters the quantity that arrived and approves in full, approves partially with a note, or rejects with a reason. Only approved quantities are credited. The sender cannot approve receipt. A shortfall stays linked to the dispatch as a discrepancy. (BE s5 steps 4-6, s13)
- Discrepancy resolution: any admin role (not Front Staff), within the branches it may act in. (BE s5; OVR s1 #13; GAP-C08)
- Sales: price from the price list (see conflict 2), stock deducted, sale record, ledger entry and audit event succeed or fail together. Completed sales are never edited; statuses are Completed, Cancelled, Refunded, Exchanged. (BE s6; OVR s1 #14; GAP-H05)
- Items: created Draft, then Active; only Active can be received, assigned or sold. Items with history are Discontinued, not deleted. (BE s3.9)
- MVP acceptance criteria are in BE s13 "MVP".

## 5. Non-functional rules

- Money: fixed-point decimal in GHS, two decimal places, never floating point. (BE s3.2; SKILLS.md Database Standards, line 97)
- Time: timezone-aware timestamps, Africa/Accra. (BE s11)
- Audit: append-only, no application role can edit or delete. Each event records user ID, role and workspace, active branch, action, reference, previous and new values, timestamp, IP or device. (BE s9)
- Permissions are enforced server-side, not by the screens. (BE s2, s11; OVR s3)
- Cost visibility: Super Admin and Warehouse Admin only. Selling price is set by Super Admin or a role with Manage prices. (OVR s1 #7)
- Cross-branch lookup: any logged-in user sees branch name and quantity only, no prices, costs, customers or sales. An explicit exception to branch isolation; isolation tests must allow it. (BE s2; OVR s2)
- Security and testing: hashed passwords, secure sessions, login rate limiting, HTTPS, secrets out of code; tests for permissions, isolation, partial receiving, concurrency and reversals. (BE s11)
- Contract: one OpenAPI document, one error format, paginated lists, session login, versioned URLs; errors name the field at fault. (OVR s3)

## 6. Out of scope for Sprints 1-2

Barcodes, labels, scanning, per-piece records, serial numbers / per-piece tracking, repair tracking, POS, label printers, bundles, stocktake, email and SMS, offline mode (BE s14; OVR s1 #4). Not before Sprint 3: full specification fields, warranty, product/variant split, several images (OVR s4; GAP-H03, H04). Not before Sprint 4: branch-to-branch transfers, adjustments, notifications. Not before Sprint 5: access requests, multi-role, price history. Not before Sprint 6: price lists, discounts, receipts, customer details. Later: split payments, daily close, refunds, reports, exports, website API, supplier records, inspection and grading. Lead capture and AI agent are unscheduled. (OVR s4; BE s10, s12)

## 7. Conflicts noticed (not resolved here)

1. **Stock buckets and the unaccepted remainder.** BE s3.8 lists on hand, reserved, in transit, quarantined or damaged and available (BE s4 omits on hand); SPEC s11.1-11.2 define no quarantined/damaged bucket and do not define "in-transit quantity". Also, SPEC s11.3 (background) says "Do not release reserved stock back to the sender until the discrepancy or return outcome is resolved according to policy." and "Record dispatched quantity, physically received quantity, accepted quantity and rejected quantity separately.", while BE s3.8 says "receipt clears the reservation" and is silent on the unaccepted remainder. Unresolved. (BE s3.8, s4 vs SPEC s11.1-11.3)
2. **Source of the selling price in the MVP.** BE s3.2 and s3.7 say price comes from the price list; BE Sprint 2 Day 6 says "price from the item"; the price list is Sprint 6 (BE Day 26). GAP-M08 only recommends a one-row-per-SKU price table and is not decided. (BE s3.2/s3.7 vs s12; GAP-M08)

Wording differences (no conflict): BE s2 says warehouse-to-branch assignment is "Warehouse Admin (and Super Admin)" while BE s5 and Day 5 say "Warehouse Admin only"; these reconcile through Super Admin powers (BE s2) and "can do everything any user can do, in every branch" (OVR s1 #2).

The owner's own list C1-C8 is not available to this digest and is not reproduced; it may overlap with the above.

## 8. Open questions

See OPEN QUESTIONS in `TASKS.md` (not answered here). Still open there: OQ-2 hosting, OQ-3 retention, OQ-7 T.2 substitution, OQ-8 B1.0/T.6, OQ-9 DRF stubs, OQ-10 coverage floor, OQ-11 psycopg licence and PG version, OQ-12 T.6. Also open in GAP: GAP-H07 tax on receipts, GAP-M07 supplier name, GAP-M08 price table, GAP-M11 menu. The cost-method note in BE s3.7 ("any other method needs to be confirmed") is unanswered.

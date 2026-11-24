# Permission Table (B1.1)

**Approved by owner 2026-11-23.**

Status: **approved** (TASKS B1.1, OVR decision 15). Owner approved OQ-4 to OQ-19 as written on 2026-11-23; their answers are folded into the cells below. OQ-20 and OQ-21 (item API details) are still open.
Scope: MVP actions, Sprint 1 and Sprint 2. Later-sprint actions are listed once at the end so the model stays ready for them.
Rows the docs did not state were answered by the owner in TASKS "Open questions" (OQ-4 to OQ-19, approved 2026-11-23); the source column cites the OQ.

Source keys: **OVR** = 1-Overview-and-Sprints, **FE** = 2-Frontend, **BE** = 3-Backend, **GAPS** = PROJECT_GAPS_AND_ACTIONS, **DEC** = workspace CLAUDE.md "Decisions already made", **SPEC** = 6-Functional-Workflow-Specification (background).

Legend: Y = allowed. N = not allowed. SA = Super Admin, WA = Warehouse Admin, BA = Branch Admin, FS = Front Staff. "Own branch" = the user's active branch (BA: permanent branch; FS: the working branch they chose). Every Y is also subject to the branch rules in section 2 and is enforced on the server.

## 1. Roles and places

| Role | Works in | Source |
|---|---|---|
| SA | Everything, every branch and the warehouse. Own ID format `SA-0001`. | BE s2, OVR 2 |
| WA | The central warehouse. Neutral ID `USR-0001`. | BE s2, FE s3 |
| BA | One permanent branch. | BE s2 |
| FS | Any active branch, chosen after login; switching is logged. | BE s2, OVR 1, GAPS C05 |

One account per person. Only SA can assign more than one role (role switching is Sprint 5, out of the MVP).

## 2. Branch and access rules (apply to every row below)

1. Every request is scoped by the server to the user's active branch (or the warehouse for WA). The client never chooses the scope. (BE s2)
2. FS pick any active branch after login; every request then uses it; each switch is logged. (BE s2, OVR 1)
3. BA and WA have one permanent location. Temporary access elsewhere needs an approved request (BE s2). **That request flow is Sprint 5**, so in the MVP BA and WA cannot act outside their location. (BE s12)
4. SA acts in every location. Each action is recorded under the SA's own ID with the role and branch used. (BE s2)
   Owner decision 2026-11-24: the SA is never asked to pick a branch at login. SA lists, users and the dashboard show all branches by default, with an optional `?branch=<id>` filter to view one; every action available to SA works on any branch, and an action on a record uses that record's location (OQ-12). The server returns `must_pick_branch` true only when the role requires a working branch and none is chosen (FS); it is always false for SA.
5. **Cross-branch lookup exception:** any logged-in user sees other branches' available quantity for a selected item, as branch name and quantity only. No prices, costs, customers or sales. (BE s2, OVR 2)
6. Only active users and active branches can act; deactivated records keep their history. (BE s2)
7. Cost price is never returned for BA or FS (not hidden in the screen, not serialised). (OVR 7, TASKS 0.3)

## 3. Per-person permissions (granted by SA, from the user edit screen until Sprint 5)

| Permission | What it unlocks | Who can hold it | MVP effect | Source |
|---|---|---|---|---|
| Receive stock | Confirm a dispatch's arrival at a branch (full, partial, reject). | FS. BA and SA already have the right by role. | Yes, Sprint 1 Day 5 | OVR "Assumptions confirmed", OVR 15, BE s12 |
| Manage prices | Change the selling price in the price list. | Any role other than SA (SA has it by role). Any role may hold it (OQ-11). | Yes, price list is in the MVP | BE 3.7, OVR 7, DEC |
| Discount | Give a discount with a mandatory reason and recorded limit. | Any role (OQ-11). | **No MVP action** (Sprint 6). The flag is stored from the MVP and unused until Sprint 6 (OQ-11). | BE s6, s12 Day 28 |

Rules: only SA grants or revokes them; every grant and revoke is an audit event; a grant never widens branch scope; WA never needs "Receive stock" for the warehouse (a warehouse receipt is a WA/SA action by role).

## 4. MVP action matrix

### 4.1 Account and session

| # | Action | SA | WA | BA | FS | Notes and source |
|---|---|---|---|---|---|---|
| 1 | Log in, log out | Y | Y | Y | Y | Login ID plus password; rate limited; every login and failure is logged. BE s11, s9 |
| 2 | Change own password | Y | Y | Y | Y | DEC C5 |
| 3 | Forced password change at first login after create or reset | Y | Y | Y | Y | DEC C5 |
| 4 | Create user, edit, activate, deactivate, suspend | Y | N | N | N | OVR 2, BE s2. Suspend = temporary, reversible; deactivate = permanent, history kept; both end sessions at once (OQ-14). The last active Super Admin cannot lose the role, be suspended or deactivated (OQ-26) |
| 5 | Reset a user's password (one-time password shown once) | Y | N | N | N | DEC C5 |
| 6 | Assign a role and a permanent branch | Y | N | N | N | BE s2 |
| 7 | Assign more than one role | Y | N | N | N | BE s2 (switching itself is Sprint 5) |
| 8 | Grant or revoke per-person permissions | Y | N | N | N | OVR 15 |
| 9 | View user list, last login, session history | Y | warehouse | own branch | N | BE s2. WA and BA see their own location only (OQ-5); BA also sees Front Staff currently working at their branch (OQ-26) |
| 10 | Pick or switch working branch | Y | N | N | Y | FS any active branch (must pick before working: `must_pick_branch`); BA and WA have a fixed location. SA is never asked; SA may optionally pick a context branch and works across all branches; actions on a record use that record's location (OQ-12). BE s2 |

### 4.2 Branches

| # | Action | SA | WA | BA | FS | Notes and source |
|---|---|---|---|---|---|---|
| 11 | Create, edit, deactivate a branch | Y | N | N | N | OVR 2 |
| 12 | List active branches | Y | Y | Y | Y | FS needs it to choose; WA needs it to dispatch. FE 4.1, 4.7 |

### 4.3 Items and prices

| # | Action | SA | WA | BA | FS | Notes and source |
|---|---|---|---|---|---|---|
| 13 | View and search items (name, SKU, brand, model) | Y | Y | Y | Y | FE 4.3, 4.5; BE 3.10 |
| 14 | See cost price | Y | Y | N | N | OVR 7, DEC C12b |
| 15 | Create and edit item as Draft, activate, set Discontinued, upload the one image | Y | Y | N | N | OVR 2 "WA manages items". BA/FS view only (OQ-7). Image: JPEG, PNG or WebP, at most 5 MB. Discontinued is final, no move back (OQ-20). Activation does not need a price (OQ-21). |
| 16 | Set selling price (price list, one row per SKU, no negatives) | Y | Grant | Grant | Grant | SA or anyone holding "Manage prices". WA does not get it by role. Sending `selling_price` on item create or edit without it is 403 (OQ-21). BE 3.7, DEC |
| 17 | Set reorder level per item per location | Y | Y | N | N | DEC C13 (also via CSV) |
| 18 | Set optional bin label on a warehouse stock row | Y | Y | N | N | DEC, BE 3.8. SA and WA only (OQ-7) |
| 19 | CSV import of items and opening quantity per location (dry run, then commit) | Y | Y | N | N | BE 3.11, s12 Day 6. SA and WA only (OQ-6) |
| 20 | Opening-stock import carries unit cost, feeding average cost | Y | Y | N | N | DEC C12b. Cost visible to SA and WA only. |
| 43 | Add, rename, deactivate a brand (never deleted) | Y | Y | N | N | OQ-20 (owner, 2026-11-23). Everyone may view brands (row 13). |

Draft items cannot be received, dispatched or sold; only Active ones. (BE 3.9)

### 4.4 Stock

| # | Action | SA | WA | BA | FS | Notes and source |
|---|---|---|---|---|---|---|
| 21 | View stock balances (on hand, reserved, available, quarantined) | all locations | warehouse in full; per-branch quantities only, no cost (OQ-8) | own branch | own branch | FE 4.4 "stock by location". Branch roles never see another branch's full stock. |
| 22 | Cross-branch quantity lookup for a selected item | Y | Y | Y | Y | Branch name and quantity only. BE s2 |
| 23 | Any stock change (receipt, dispatch, receiving, sale, cancel, resolution, import) | via service only | via service only | via service only | via service only | One stock service for all, with ledger and audit rows. TASKS 0.3 |
| 24 | View stock ledger / movement history | N | N | N | N | Not an MVP screen; ledger and audit are written, history endpoints come in Sprint 5 (BE s12 Day 24). |

### 4.5 Warehouse receipt (supplier GRN)

| # | Action | SA | WA | BA | FS | Notes and source |
|---|---|---|---|---|---|---|
| 25 | Record a supplier receipt (supplier name, lines, quantity, unit cost); increases warehouse on hand | Y | Y | N | N | SPEC 4.1, 4.4 "only authorised warehouse users"; FE 4.6 |
| 26 | Edit or delete a confirmed receipt | N | N | N | N | Never silently edited; correction is an adjustment or reversal (Sprint 4). BE s4 |
| 27 | List and view receipts | Y | Y | N | N | Cost shown. BA and FS never see receipts (OQ-8) |

### 4.6 Dispatch and branch receiving

| # | Action | SA | WA | BA | FS | Notes and source |
|---|---|---|---|---|---|---|
| 28 | Create a dispatch to a branch (reserves quantity at the warehouse; in transit) | Y | Y | N | N | WA and SA only. BE s2, s5 |
| 29 | List dispatches and their status | all | all | to own branch | to own branch (when listing waiting items) | FE 4.7, 4.8 |
| 30 | See what is waiting at a branch | Y | N | own branch | own branch | BE s12 Day 5 |
| 31 | Confirm receiving: quantity received per line, approve all, approve partially (note), or reject (reason) | Y | N | Y | Grant "Receive stock" | Destination only. The sender cannot approve receipt. Only accepted quantity is credited. OVR assumptions, BE s5 |
| 32 | Cancel or edit a dispatch after creation | N | N | N | N | No cancel or amend in the MVP. Reserved stock is only released through the resolution paths (OQ-15) |

### 4.7 Shortfall (discrepancy) resolution (Sprint 2 Day 7)

| # | Action | SA | WA | BA | FS | Notes and source |
|---|---|---|---|---|---|---|
| 33 | View open shortfalls | Y | Y | Y | N | FS may not view (OQ-9a) |
| 34 | Resolve: return to sender, confirm loss, record damage (mandatory note) | Y | Y | Y | N | Any admin role, within the locations it may act in (sender warehouse: WA; destination branch: BA; SA both); FS never. OVR 13, BE s5.6, DEC, OQ-9b |
| 35 | Resolve the same person's own recorded shortfall | Y (flagged) | Y (flagged) | Y (flagged) | N | Resolution is not an approval request; the audit event is flagged when it is the same person (OQ-9c) |

For a warehouse-to-branch shortfall, WA acts for the sender side, BA for its own destination branch, SA for both (OQ-9b).

Effects per DEC: return to sender releases reserved; confirm loss releases reserved and reduces on hand; record damage releases reserved and reduces on hand at the sender and adds quarantined at the destination. Each writes ledger rows and an audit event.

### 4.8 Sales

| # | Action | SA | WA | BA | FS | Notes and source |
|---|---|---|---|---|---|---|
| 36 | Record a sale in the active branch (price from price list, payment cash, mobile money or card) | Y | N | Y | Y | Blocked when quantity exceeds available stock at that branch. Also blocked while the item has no selling price (OQ-21; B-sales must enforce). WA: not listed in WA's menu or BE s6, so N. BE s6, FE 3 |
| 37 | Override price or give a discount during a sale | N | N | N | N | Not before Sprint 6 (DEC); only with a grant even then. |
| 38 | List sales for a branch | all | N | own branch | own branch, all its sales (OQ-10) | FE 4.10 |
| 39 | Cancel a sale (reason required; reversal entry, original stays visible) | Y | N | Y (own branch) | N | OVR/BE s6, s13. Never an edit of the sale. |

### 4.9 Dashboard and activity

| # | Action | SA | WA | BA | FS | Notes and source |
|---|---|---|---|---|---|---|
| 40 | Dashboard data (stock, in transit, low stock, recent activity) | all | warehouse | own branch | N (FS has no Home tab, FE s3) | Scoped to role and branch. BE s8 |
| 41 | Activity log list (filter user, branch, action, date) | Y | warehouse | own branch | N | WA warehouse activity, BA own branch activity (OQ-5) |
| 42 | Edit or delete an audit event or ledger row | N | N | N | N | Append-only for everyone, including SA. BE s9 |

### 4.10 Menu entries and Home links (OQ-23, owner-approved 2026-11-24)

Each entry is shown only to a role that holds the row it points to. Super Admin opens these four from Home (FE s3): the server returns them as `/me` `home_links`, separate from the max-5 `menu`, so they never take a nav slot. `/me` `can_assign_multiple_roles` is true only for SA (row 7).

| # | Action | SA | WA | BA | FS | Notes and source |
|---|---|---|---|---|---|---|
| 44 | Sell entry (`sales.record`) | Y | N | Y | Y | Same as row 36. SA: Home link (FE s3). BA, FS: existing nav item. |
| 45 | Activity entry (`activity.view`) | Y | warehouse | own branch | N | Same as row 41. SA, WA, BA: Home link "Activity" (FE s3; WA and BA see only their own location, OQ-25 decided 2026-11-24). |
| 46 | Find entry (`find.use`) | Y | Y | Y | Y | Rows 13 and 22. SA: Home link (FE s3). Others: existing nav item. |
| 47 | Receive entry (`dispatches.receive`) | Y | N | Y | Grant | Same as row 31. SA: Home link (FE s3). BA, FS: existing nav item. |

## 5. Self-approval rules

1. SA may approve their own requests; every self-approval is flagged in the audit trail. (OVR 3, BE s2)
2. Every other role cannot approve their own request. (OVR 3)
3. MVP application: the user who created a dispatch cannot confirm its receipt, unless SA (flagged). The sender cannot approve receipt (BE s5, SPEC 6.2).
4. Approval-type flows (adjustments Sprint 4, branch access requests Sprint 5) reuse the same rule.
5. The person who recorded a shortfall may resolve it if an admin role; the audit event is flagged (OQ-9c).

## 6. Shortfall resolution authority (summary)

Only the admin roles (SA, WA, BA) resolve shortfalls, within the branches they may act in, with a mandatory note, through the stock service. FS can never resolve. Basic paths: return to sender, confirm loss, record damage. "Other authorised disposition" arrives with Sprint 4. (OVR 13, BE s5.6, s13 MVP)

## 7. Later-sprint actions (not built now; listed so the design stays ready)

Branch-to-branch transfers (BA, Sprint 4); stock adjustments and reversals with approval (Sprint 4); notifications (Sprint 4); temporary branch access request and approval, by the destination BA or SA (Sprint 5); multi-role assignment and role switching (Sprint 5); price history and below-cost warning (Sprint 5); price override per branch, discounts, receipts, customer details (Sprint 6); split payments, daily close, refunds (Sprint 7); reports and exports (Sprint 8); website API key management, grading, supplier records (Sprint 9).

## 8. Decided and open points

OQ-4 to OQ-19 were approved by the owner on 2026-11-23 and are folded into the cells above (IDs immutable, OQ-4; user list and activity log scope, OQ-5; CSV import, OQ-6; item management, OQ-7; WA stock view, OQ-8; shortfalls, OQ-9; FS sales list, OQ-10; Manage prices and Discount holders, OQ-11; SA context branch, OQ-12; login limits 5 per 15 minutes, 10-character passwords, 72-hour one-time password, OQ-13; suspend vs deactivate, OQ-14; no dispatch cancel in the MVP, OQ-15).

OQ-20 (brand management by SA and WA, 5 MB JPEG/PNG/WebP image, Discontinued final, dashboard fields as in the contract) and OQ-21 (only SA or a Manage prices holder sends `selling_price`; activation needs no price; sale blocked until a price exists) were approved by the owner on 2026-11-23 (contract v0.1.1). Contract v0.1.1 also limits `GET /working-branch/` to FS and SA (row 10) and serves cost only through SA/WA operations (row 14).

Still **OPEN**: OQ-22 (when an account is `pending_activation`).

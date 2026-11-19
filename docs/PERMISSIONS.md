# Scope and permission table (B1.1)

**Status: DRAFT for owner approval (gate).** Nothing here is built yet. Changing a row after approval is a requirements change and needs the owner. Sprints 1 and 2 only (MVP, `v1.0.0`).

Sources are cited as in `REQUIREMENTS-DIGEST.md`: **BE** = `3-Backend-Requirements.md`, **OVR** = `1-Overview-and-Sprints.md`, **FE** = `2-Frontend-Requirements.md`, **GAP** = `PROJECT_GAPS_AND_ACTIONS.md`, **SPEC** = `6-Functional-Workflow-Specification.md` (background per GAP-C04), **SKILLS** = `SKILLS.md`, **OQ-n** = owner decisions of 2026-11-19 recorded in `TASKS.md` / `.claude/STATE.md`. Where this draft and a source differ, the source wins (GAP-C04). Anything the sources do not decide is marked **OPEN** with a question in section 8. Nothing is guessed: a proposed default is only a proposal.

Companion document: `docs/ERD.md` (B1.2).

## 1. Scope of Sprints 1 and 2 (what the matrix covers)

In scope (B1.x to B8.x): login and sessions, working-branch selection, branch and user management, per-person permissions, items (Draft, Active, one image), the central price list (one row per SKU, OQ-19), stock balances and the stock ledger, warehouse receipts, dispatches to branches, branch receiving with shortfall flagging, basic shortfall resolution (return, loss, damage), sales and cancel, cross-branch lookup, CSV import with opening balances, dashboard and activity log.

Out of scope here (Sprint 3 and later; no rows in the matrix): full specification fields, warranty, product/variant split, several images, branch-to-branch transfers, adjustments and approvals, notifications, branch access requests, multi-role assignment and role switching, price history and below-cost warning, price lists with branch overrides, discounts, receipts, customer details, split payments, daily close, refunds, reports, exports, website API, supplier records, inspection and grading, barcodes, per-piece tracking (BE s14; OVR s4; digest s6).

Not in the TASKS B steps, so not in the matrix and not designed: changing one's own password, forgotten-password self-service, session listing. Add a row (with approval) if wanted.

## 2. Roles

Four roles; one account per person; only a Super Admin assigns more than one role (BE s2). Sprints 1 and 2 build single-role use; multi-role and the role switcher are Sprint 5 (B22.x), so the matrix has one column per role.

| Role | Code | Scope in Sprints 1-2 | Source |
|---|---|---|---|
| Super Admin | SA | Everything, in every branch and the warehouse. Manages accounts, roles, branches and prices. Sees cost. May approve their own requests; each self-approval is flagged in the audit trail. Acts under their own ID with the role and branch used. | BE s2; OVR s1 #2, #3, #7 |
| Warehouse Admin | WA | One permanent location: the central warehouse. Manages items, receives supplier stock into the warehouse, dispatches to branches, resolves shortfalls on dispatches they may act on. Sees cost. Does not sell and does not receive at branches (see P2). | OVR s2; BE s2, s4, s5; FE 3 |
| Branch Admin | BA | One permanent branch. Receives at their branch, sells, cancels sales at their branch, resolves shortfalls within their allowed branches, sees branch stock. No cost. | OVR s2; BE s5, s6 |
| Front Staff | FS | No fixed branch: picks any active branch after login (each switch logged); all requests are then scoped to it. Sells, finds items, sees the branch's stock; receives at a branch only with the Receive stock permission. No cost. Cannot resolve shortfalls or cancel sales. | BE s2; OVR s1 #1, s2; GAP-C05, GAP-C08 |

Login IDs: Super Admins `SA-0001` style; everyone else `USR-0001` style; system-generated, never changed, never reused (BE s2; OVR s1 #2).

## 3. Per-person permissions

Granted and revoked by a Super Admin from the user edit screen (B3.3) until the Sprint 5 role screen. Each grant or revoke is audited with the granter.

| Code | Meaning | Enforced in Sprints 1-2? | Source |
|---|---|---|---|
| `receive_stock` | May confirm receiving at the **active branch** for dispatches addressed to it (approve all, partial, reject). Does not allow warehouse receipts. Branch Admin has this inherently. | Yes (`dispatch.receive`) | OVR s1 assumptions, #15; BE Sprint 1 Day 3; see P6 |
| `manage_prices` | May set or change the central selling price of an SKU. Super Admin has this inherently. | Yes (`price.set`, OQ-19) | OVR s1 #7, #15; BE s3.7; OQ-19 |
| `apply_discount` | May give a discount with mandatory reason and recorded limit. | No: defined and grantable now, enforced from Sprint 6 (B28.1). The sale API in Sprints 1-2 accepts no discount. | BE s6; OVR s1 #15; TASKS B1.1 |

Assumption to confirm (P16): any permission can be granted to any role (holding it as Super Admin or, for `receive_stock`, Branch Admin is a no-op). A grant never widens branch scope: `receive_stock` applies only at the active branch.

## 4. Branch rules

1. Every request is scoped server-side to the **active branch** from the session. The client never supplies it as a trusted value (BE s2, s11).
2. Front Staff: any **active** branch, picked after login, switchable, every switch logged (audit event `branch.switched`) (BE s2; GAP-C05). Whether the warehouse is selectable: P17.
3. Warehouse Admin and Branch Admin: one permanent location. Temporary access to another branch is Sprint 5 (B21.1) and is **denied** in Sprints 1-2.
4. Super Admin: every location. Whether a Super Admin selects an active branch like others: P1.
5. Deactivated branches cannot be selected or sold from; their history stays (SPEC 3.1).
6. **Branch isolation exception:** any signed-in user may see other branches' available quantity for an item, as branch name and quantity only. No prices, costs, customers or sales (BE s2; OVR s2). Isolation tests must allow exactly this and nothing else.
7. Warehouse-to-branch assignment (dispatch) is Warehouse Admin and Super Admin only (BE s2, s5).
8. Suspended or deactivated users cannot log in; their history stays.

## 5. Approval and self-approval rules

- Super Admin may approve their own requests; every such action writes an audit event with `self_approved = true` (OVR s1 #3; BE s2; SKILLS Approvals).
- Nobody else may approve their own request (same sources).
- In Sprints 1-2 the only approval-like decision is the **receiving decision** at the destination: the sender cannot approve receipt (BE s5 step 5). Rule applied here (`not_self`): the user who dispatched cannot record the receiving decision. Only a Super Admin who both dispatched and received may do so, flagged.
- The approval workflow tables (`approvals` app) are Sprint 4 (adjustments). Not built now.
- Open: whether the receiver may also resolve their own shortfall (P9) and whether a Branch Admin may cancel a sale they recorded (P19).

## 6. Shortfall resolution (GAP-C08, OVR s1 #13)

- Resolution paths: return to sender, confirm loss, record damage; a **note is mandatory**; goes through the stock service with ledger and audit entries (B7.3, BE Sprint 2 Day 7).
- Who: any admin role (Super Admin, Warehouse Admin, Branch Admin), **within the branches it may act in**. Front Staff are refused, even with Receive stock.
- Meaning of "allowed branches" for a dispatch (origin warehouse or destination branch, or both): P8.

## 7. Cost and price visibility

- **Cost price** (receipt unit cost and anything derived from it) is visible to Super Admin and Warehouse Admin only. For Branch Admin and Front Staff it is **never serialised**: the field is absent from every response, not null or masked (OVR s1 #7; SKILLS Sensitive data). Tested per endpoint.
- **Selling price** is visible to every role that sells or finds items. It is set by a Super Admin or a `manage_prices` holder, never negative.
- **Cross-branch lookup** returns branch name and available quantity only.
- The website API exposes no cost (Sprint 9; not in scope here).

## 8. The permission matrix (Sprints 1-2)

55 rows. Columns: SA Super Admin, WA Warehouse Admin, BA Branch Admin, FS Front Staff.

How to read a cell:
- **Allow**: allowed, no extra condition beyond the global preconditions below.
- **Deny**: refused (HTTP 403, or 404 where the object must not be revealed; B1.3 decides per endpoint). Every Deny is a test.
- **If `a` + `b`**: allowed only when all conditions hold; otherwise refused.
- **OPEN Pn**: not decided by the documents; see section 10. Not to be built or tested until answered.

Global preconditions for every row except `auth.login`: authenticated session (else 401), account Active, active branch valid for the user (section 4). The conditions:

| Condition | Meaning |
|---|---|
| `own_branch` | The resource's branch equals the caller's active branch, and the caller may use it (FS: any active branch; BA: permanent branch). SA passes for any. |
| `own_location` | Same, for the WA's permanent location (the warehouse). |
| `any_active_branch` | FS may choose any active branch. |
| `active_id_name_only` | Only id and name of active branches are returned. |
| `active_items_only` | BA and FS see Active items only (proposed, P4). |
| `origin_is_own_location` | The dispatch's origin is the caller's location. |
| `destination_is_active_branch` | The dispatch's destination is the caller's active branch. |
| `allowed_branch` | The dispatch's origin or destination is a location the caller may act in (proposed reading, P8). |
| `perm:<code>` | The caller holds that per-person permission (section 3). |
| `not_self` | The caller did not dispatch it (section 5). |
| `flag_if_self` | Allowed; if the caller is also the actor on the other side, the audit event is flagged `self_approved`. |

### 8.1 Table

| # | Action ID | Step | Action | SA | WA | BA | FS | Source | Notes |
|---|---|---|---|---|---|---|---|---|---|
| 1 | `auth.login` | B2.3 | Log in with login ID and password (active accounts only) | Allow | Allow | Allow | Allow | BE s2, s11; SKILLS Authentication | Unauthenticated endpoint. Suspended or deactivated accounts are refused. Rate limited, every attempt logged (P18). |
| 2 | `auth.logout` | B2.3 | Log out | Allow | Allow | Allow | Allow | BE s9 (logouts audited) | Any signed-in user. |
| 3 | `auth.me` | B2.4 | Read own profile, role, active branch, per-person permissions | Allow | Allow | Allow | Allow | OVR s3 (menus built from what the user may do) | Returns only the caller's own data; the frontend builds its menu from this. |
| 4 | `context.list_selectable` | B3.1 | List the branches I may work in | Allow | If `own_location` | If `own_branch` | If `any_active_branch` | BE s2; OVR s1 #1; GAP-C05 | Front Staff: every active branch (P17 on the warehouse). WA and BA: their one permanent location only (temporary access is Sprint 5). SA: all. |
| 5 | `context.select_branch` | B3.1 | Select the working branch after login | **OPEN P1** | If `own_location` | If `own_branch` | If `any_active_branch` | BE s2; FE 4.1 | Server scopes every later request to it. WA/BA have no real choice (default workspace). |
| 6 | `context.switch_branch` | B3.1 | Switch the working branch (each switch logged) | **OPEN P1** | If `own_location` | If `own_branch` | If `any_active_branch` | BE s2; GAP-C05; SPEC 3.1 | Audit event branch.switched. Temporary access to other branches is Sprint 5 (B21.1), so denied for WA/BA now. |
| 7 | `branch.list` | B3.2 | List branches | Allow | If `active_id_name_only` | If `own_branch` | If `active_id_name_only` | SPEC 3.1; FE 4.1, 4.7 | SA: all incl. inactive with contact details. WA: active branches (id, name) to choose a dispatch destination. FS: the selectable list. BA: own branch only. |
| 8 | `branch.create` | B3.2 | Create a branch | Allow | Deny | Deny | Deny | SPEC 3.1 (Super Admin creates a branch); OVR s2 |  |
| 9 | `branch.edit` | B3.2 | Edit a branch | Allow | Deny | Deny | Deny | SPEC 3.1; OVR s2 |  |
| 10 | `branch.deactivate` | B3.2 | Deactivate or reactivate a branch (history kept) | Allow | Deny | Deny | Deny | SPEC 3.1; BE s2 | Deactivated branches cannot be selected or sold from; their records stay. |
| 11 | `user.list` | B3.3 | List users | Allow | Deny | Deny | Deny | FE 4.12 (Super Admin); SPEC 2.1 | Denial of other roles follows FE 4.12 and SPEC 2.1 (user management is Super Admin). |
| 12 | `user.read` | B3.3 | View a user (roles, branch, permissions, last login) | Allow | Deny | Deny | Deny | BE s2; FE 4.12 |  |
| 13 | `user.create` | B3.3 | Create a user (auto login ID, role, permanent branch) | Allow | Deny | Deny | Deny | SPEC 2.1; OVR s1 #2 | ID is SA-#### for Super Admins, USR-#### for all others; never changed, never reused. |
| 14 | `user.edit` | B3.3 | Edit a user (name, permanent branch) | Allow | Deny | Deny | Deny | SPEC 2.5 |  |
| 15 | `user.assign_role` | B2.4/B3.3 | Assign or change roles (more than one role only by Super Admin) | Allow | Deny | Deny | Deny | BE s2; OVR s1 #2; SPEC 2.1, 2.4 | Users cannot grant roles to themselves. Multiple roles and role switching are Sprint 5. |
| 16 | `user.set_status` | B3.3 | Activate, deactivate or suspend a user | **OPEN P15** | Deny | Deny | Deny | BE s2; SPEC 2.5 | History preserved. Question: may a Super Admin deactivate themselves or the last active Super Admin. |
| 17 | `user.reset_password` | B3.3 | Reset a user's password | Allow | Deny | Deny | Deny | BE s2; B3.3 |  |
| 18 | `user.grant_permission` | B3.3 | Grant or revoke a per-person permission (receive_stock, manage_prices, apply_discount) | Allow | Deny | Deny | Deny | OVR s1 #15; GAP-C06; BE Sprint 1 Day 3 | Super Admin only, from the user edit screen until the Sprint 5 role screen. Each grant and revoke is audited. |
| 19 | `dashboard.shell` | B3.4 | Dashboard shell data (menu, home basics) | Allow | Allow | Allow | Allow | BE Sprint 1 Day 3 | Content is built from the caller's own permissions. |
| 20 | `dashboard.stats` | B7.1 | Dashboard figures: stock per branch, in transit, low stock | Allow | **OPEN P12** | If `own_branch` | Deny | BE s8, Sprint 2 Day 7; FE 3, 4.2 | FS has no Home in the menu (FE s3), so denied. WA scope (warehouse only or all) is open. In-transit definition: ERD E5. |
| 21 | `activity.list` | B7.2 | Activity log (filter by user, branch, action, date) | Allow | **OPEN P12** | **OPEN P12** | **OPEN P12** | BE s9, Sprint 2 Day 7; FE 4.13 | Docs give the screen but not who may see which events. Proposed: SA all, BA own branch only, WA own location, FS none. |
| 22 | `item.read` | B4.1 | List and read items (selling price included, cost excluded) | Allow | Allow | If `active_items_only` | If `active_items_only` | OVR s2; FE 4.3, 4.5, 4.9 | BA and FS need items to sell, find and count stock. Draft visibility: P4. |
| 23 | `item.field_definitions` | B4.1 | Read item field definitions per category | Allow | Allow | Deny | Deny | BE Sprint 1 Day 4; FE 4.3 | Used by the item form, which only SA and WA see. |
| 24 | `item.create` | B4.1 | Create an item (Draft) | Allow | Allow | Deny | Deny | OVR s2 (Warehouse Admin manages items); BE s3.9 |  |
| 25 | `item.edit` | B4.1 | Edit an item (audited with before and after) | Allow | Allow | Deny | Deny | OVR s2; BE s3.9 |  |
| 26 | `item.activate` | B4.1 | Make an item Active | Allow | Allow | Deny | Deny | BE s3.9; OVR s2 | Whether activation needs a price: P5. |
| 27 | `item.discontinue` | B4.1 | Mark an item Discontinued | Allow | Allow | Deny | Deny | BE s3.9; OVR s2 | Items with history are never deleted. |
| 28 | `item.upload_image` | B4.2 | Upload the item image (type and size enforced) | Allow | Allow | Deny | Deny | BE s3.6; B4.2 |  |
| 29 | `field.cost.read` | B4.1 | See cost price on any response | Allow | Allow | Deny | Deny | OVR s1 #7; OVR s2; BE s3.2; SKILLS Sensitive data | Field-level rule: cost is not serialised at all for BA and FS (absent, not null). |
| 30 | `price.read` | B6.1 | Read the selling price (price list) | Allow | Allow | Allow | Allow | OVR s1 #7; FE 4.9 | Not part of the cross-branch lookup (that shows name and quantity only). |
| 31 | `price.set` | B6.1 | Set or change the selling price of an SKU (not negative) | Allow | If `perm:manage_prices` | If `perm:manage_prices` | If `perm:manage_prices` | OVR s1 #7; BE s3.7; OQ-19 | Central price list, one row per SKU. Every change is audited with old and new values. Who sets the first price of a WA-created item: P5. |
| 32 | `stock.list_own_location` | B4.4 | Stock balances at my active location (available, on hand, reserved, quarantined) | Allow | If `own_location` | If `own_branch` | If `own_branch` | FE 4.4; BE s2 | Cost never included for BA and FS. Branch isolation applies. |
| 33 | `stock.list_other_locations` | B4.4 | Stock balances at locations other than my own (full figures) | Allow | **OPEN P13** | Deny | Deny | SKILLS Unauthorised operations (no other branch's data except the lookup) | WA seeing branch balances to plan dispatches: P13. |
| 34 | `find.search` | B6.3 | Search items by name, SKU, brand, model with stock at my location | Allow | Allow | Allow | Allow | BE s3.10; FE 4.5 |  |
| 35 | `stock.lookup_other_branches` | B6.3 | Cross-branch lookup: other branches' available quantity | Allow | Allow | Allow | Allow | BE s2; OVR s2; SKILLS Authentication | Branch name and quantity only. No prices, costs, customers or sales. Explicit exception to isolation. Whether the warehouse is listed: P14. |
| 36 | `grn.create` | B5.1 | Record a warehouse receipt (supplier, lines, quantity, unit cost) | Allow | Allow | Deny | Deny | BE s4; SPEC 4.1, 4.4 (only authorised warehouse users); FE 4.6 | Idempotency key required. Never edited afterwards. Receive stock permission scope: P6. |
| 37 | `grn.read` | B5.1 | List and read warehouse receipts (cost visible) | Allow | Allow | Deny | Deny | BE s4; OVR s1 #7 | Receipts carry cost, so only cost-visible roles read them. |
| 38 | `dispatch.create` | B5.2 | Dispatch stock from the warehouse to a branch | Allow | If `own_location` | Deny | Deny | BE s2 (assignment restricted to Warehouse Admin and Super Admin), s5; TASKS B5.2; Digest s7 | Validates available stock. SA allowed through full powers (OVR s1 #2). |
| 39 | `dispatch.list_sent` | B5.2 | List dispatches sent from my location | Allow | If `origin_is_own_location` | Deny | Deny | FE 4.7 |  |
| 40 | `dispatch.list_incoming` | B5.4 | List what is waiting at my active branch | Allow | Deny | If `destination_is_active_branch` | **OPEN P7** | BE Sprint 1 Day 5; FE 4.8 | FS: with or without the Receive stock permission, P7. |
| 41 | `dispatch.read` | B5.3 | Read one dispatch with its lines and discrepancies | Allow | If `origin_is_own_location` | If `destination_is_active_branch` | **OPEN P7** | FE 4.7, 4.8 | Cost never shown. |
| 42 | `dispatch.receive` | B5.3 | Receiving decision: approve all, approve partially (note), reject (reason) | If `flag_if_self` | Deny | If `destination_is_active_branch` + `not_self` | If `destination_is_active_branch` + `perm:receive_stock` + `not_self` | BE s5 steps 4-6, s13; OVR s1 #3, assumptions (who confirms receipt) | The sender cannot approve. SA on own dispatch: allowed, flagged. Credits accepted quantity only. Idempotency key required. |
| 43 | `discrepancy.read` | B5.3/B7.3 | List and read dispatch discrepancies | Allow | If `allowed_branch` | If `allowed_branch` | **OPEN P7** | BE s5 step 6; FE 4.8 | FS sees the flag on the dispatch they receive; a separate list is open (P7). |
| 44 | `discrepancy.resolve_return` | B7.3 | Resolve: return to sender (note required) | Allow | If `allowed_branch` | If `allowed_branch` | Deny | GAP-C08; OVR s1 #13; BE s5 step 6; TASKS B7.3 | Any admin role within its allowed branches; front staff refused. Meaning of allowed branch: P8. Same actor as the receiver: P9. |
| 45 | `discrepancy.resolve_loss` | B7.3 | Resolve: confirm loss (note required) | Allow | If `allowed_branch` | If `allowed_branch` | Deny | GAP-C08; BE s5 step 6 | As above. |
| 46 | `discrepancy.resolve_damage` | B7.3 | Resolve: record damage (note required) | Allow | If `allowed_branch` | If `allowed_branch` | Deny | GAP-C08; BE s5 step 6 | As above. |
| 47 | `sale.create` | B6.1 | Record a sale at my active branch | Allow | **OPEN P2** | If `own_branch` | If `own_branch` | BE s6; OVR s2; FE 4.9 | Price comes from the price list; no price field is accepted from the client (P11). Overselling blocked. Idempotency key required. |
| 48 | `sale.list` | B6.2 | List sales for a branch | Allow | **OPEN P2** | If `own_branch` | **OPEN P10** | BE s6; FE 4.10 | FS: own sales only or the whole branch, P10. |
| 49 | `sale.read` | B6.2 | Read one sale | Allow | **OPEN P2** | If `own_branch` | **OPEN P10** | BE s6 |  |
| 50 | `sale.cancel` | B6.5 | Cancel a sale (reason required, linked reversal) | Allow | Deny | If `own_branch` | Deny | BE s6, Sprint 2 Day 6; FE 4.10 | Super Admin and Branch Admin only. Cancelling a sale one recorded oneself: P19. |
| 51 | `import.dry_run` | B6.4 | CSV import dry run (row-numbered error report) | Allow | **OPEN P3** | **OPEN P3** | **OPEN P3** | BE s3.11; TASKS B6.4 | Docs name no role. Proposed: SA and WA. |
| 52 | `import.commit` | B6.4 | CSV import commit (items and opening balances as ledger movements) | Allow | **OPEN P3** | **OPEN P3** | **OPEN P3** | BE s3.11; TASKS B6.4 | Idempotency key required. Whether opening balances may be loaded for branch locations by WA: P3. |
| 53 | `ledger.modify` | B4.3 | Update or delete a stock ledger row (no path exists) | Deny | Deny | Deny | Deny | BE s9; SKILLS Database Standards | Includes Super Admin. Tested at model, queryset and database level. |
| 54 | `audit.modify` | B4.3 | Update or delete an audit row (no path exists) | Deny | Deny | Deny | Deny | BE s9; SKILLS Database Standards | Includes Super Admin. |
| 55 | `stock.edit_balance_directly` | B4.3 | Edit a stock balance outside the stock service (no path exists) | Deny | Deny | Deny | Deny | BE s3.11, s11; TASKS B4.3 | Corrections are service-made movements only. |

### 8.2 Machine-readable matrix (source for the permission tests)

`id` values are stable test keys: do not rename after approval. Cell forms: `allow`, `deny`, `{allow_if: [conditions]}`, `{open: Pn}`. The qa-tester generates one parametrised test per action and role from this block; an `open` cell has no test until answered. The table above and this block are produced from the same data and must stay identical.

```yaml
version: 1
roles: [SA, WA, BA, FS]
actions:
  - id: auth.login
    step: "B2.3"
    SA: allow
    WA: allow
    BA: allow
    FS: allow
  - id: auth.logout
    step: "B2.3"
    SA: allow
    WA: allow
    BA: allow
    FS: allow
  - id: auth.me
    step: "B2.4"
    SA: allow
    WA: allow
    BA: allow
    FS: allow
  - id: context.list_selectable
    step: "B3.1"
    SA: allow
    WA: {allow_if: [own_location]}
    BA: {allow_if: [own_branch]}
    FS: {allow_if: [any_active_branch]}
  - id: context.select_branch
    step: "B3.1"
    SA: {open: P1}
    WA: {allow_if: [own_location]}
    BA: {allow_if: [own_branch]}
    FS: {allow_if: [any_active_branch]}
  - id: context.switch_branch
    step: "B3.1"
    SA: {open: P1}
    WA: {allow_if: [own_location]}
    BA: {allow_if: [own_branch]}
    FS: {allow_if: [any_active_branch]}
  - id: branch.list
    step: "B3.2"
    SA: allow
    WA: {allow_if: [active_id_name_only]}
    BA: {allow_if: [own_branch]}
    FS: {allow_if: [active_id_name_only]}
  - id: branch.create
    step: "B3.2"
    SA: allow
    WA: deny
    BA: deny
    FS: deny
  - id: branch.edit
    step: "B3.2"
    SA: allow
    WA: deny
    BA: deny
    FS: deny
  - id: branch.deactivate
    step: "B3.2"
    SA: allow
    WA: deny
    BA: deny
    FS: deny
  - id: user.list
    step: "B3.3"
    SA: allow
    WA: deny
    BA: deny
    FS: deny
  - id: user.read
    step: "B3.3"
    SA: allow
    WA: deny
    BA: deny
    FS: deny
  - id: user.create
    step: "B3.3"
    SA: allow
    WA: deny
    BA: deny
    FS: deny
  - id: user.edit
    step: "B3.3"
    SA: allow
    WA: deny
    BA: deny
    FS: deny
  - id: user.assign_role
    step: "B2.4/B3.3"
    SA: allow
    WA: deny
    BA: deny
    FS: deny
  - id: user.set_status
    step: "B3.3"
    SA: {open: P15}
    WA: deny
    BA: deny
    FS: deny
  - id: user.reset_password
    step: "B3.3"
    SA: allow
    WA: deny
    BA: deny
    FS: deny
  - id: user.grant_permission
    step: "B3.3"
    SA: allow
    WA: deny
    BA: deny
    FS: deny
  - id: dashboard.shell
    step: "B3.4"
    SA: allow
    WA: allow
    BA: allow
    FS: allow
  - id: dashboard.stats
    step: "B7.1"
    SA: allow
    WA: {open: P12}
    BA: {allow_if: [own_branch]}
    FS: deny
  - id: activity.list
    step: "B7.2"
    SA: allow
    WA: {open: P12}
    BA: {open: P12}
    FS: {open: P12}
  - id: item.read
    step: "B4.1"
    SA: allow
    WA: allow
    BA: {allow_if: [active_items_only]}
    FS: {allow_if: [active_items_only]}
  - id: item.field_definitions
    step: "B4.1"
    SA: allow
    WA: allow
    BA: deny
    FS: deny
  - id: item.create
    step: "B4.1"
    SA: allow
    WA: allow
    BA: deny
    FS: deny
  - id: item.edit
    step: "B4.1"
    SA: allow
    WA: allow
    BA: deny
    FS: deny
  - id: item.activate
    step: "B4.1"
    SA: allow
    WA: allow
    BA: deny
    FS: deny
  - id: item.discontinue
    step: "B4.1"
    SA: allow
    WA: allow
    BA: deny
    FS: deny
  - id: item.upload_image
    step: "B4.2"
    SA: allow
    WA: allow
    BA: deny
    FS: deny
  - id: field.cost.read
    step: "B4.1"
    SA: allow
    WA: allow
    BA: deny
    FS: deny
  - id: price.read
    step: "B6.1"
    SA: allow
    WA: allow
    BA: allow
    FS: allow
  - id: price.set
    step: "B6.1"
    SA: allow
    WA: {allow_if: [perm:manage_prices]}
    BA: {allow_if: [perm:manage_prices]}
    FS: {allow_if: [perm:manage_prices]}
  - id: stock.list_own_location
    step: "B4.4"
    SA: allow
    WA: {allow_if: [own_location]}
    BA: {allow_if: [own_branch]}
    FS: {allow_if: [own_branch]}
  - id: stock.list_other_locations
    step: "B4.4"
    SA: allow
    WA: {open: P13}
    BA: deny
    FS: deny
  - id: find.search
    step: "B6.3"
    SA: allow
    WA: allow
    BA: allow
    FS: allow
  - id: stock.lookup_other_branches
    step: "B6.3"
    SA: allow
    WA: allow
    BA: allow
    FS: allow
  - id: grn.create
    step: "B5.1"
    SA: allow
    WA: allow
    BA: deny
    FS: deny
  - id: grn.read
    step: "B5.1"
    SA: allow
    WA: allow
    BA: deny
    FS: deny
  - id: dispatch.create
    step: "B5.2"
    SA: allow
    WA: {allow_if: [own_location]}
    BA: deny
    FS: deny
  - id: dispatch.list_sent
    step: "B5.2"
    SA: allow
    WA: {allow_if: [origin_is_own_location]}
    BA: deny
    FS: deny
  - id: dispatch.list_incoming
    step: "B5.4"
    SA: allow
    WA: deny
    BA: {allow_if: [destination_is_active_branch]}
    FS: {open: P7}
  - id: dispatch.read
    step: "B5.3"
    SA: allow
    WA: {allow_if: [origin_is_own_location]}
    BA: {allow_if: [destination_is_active_branch]}
    FS: {open: P7}
  - id: dispatch.receive
    step: "B5.3"
    SA: {allow_if: [flag_if_self]}
    WA: deny
    BA: {allow_if: [destination_is_active_branch, not_self]}
    FS: {allow_if: [destination_is_active_branch, perm:receive_stock, not_self]}
  - id: discrepancy.read
    step: "B5.3/B7.3"
    SA: allow
    WA: {allow_if: [allowed_branch]}
    BA: {allow_if: [allowed_branch]}
    FS: {open: P7}
  - id: discrepancy.resolve_return
    step: "B7.3"
    SA: allow
    WA: {allow_if: [allowed_branch]}
    BA: {allow_if: [allowed_branch]}
    FS: deny
  - id: discrepancy.resolve_loss
    step: "B7.3"
    SA: allow
    WA: {allow_if: [allowed_branch]}
    BA: {allow_if: [allowed_branch]}
    FS: deny
  - id: discrepancy.resolve_damage
    step: "B7.3"
    SA: allow
    WA: {allow_if: [allowed_branch]}
    BA: {allow_if: [allowed_branch]}
    FS: deny
  - id: sale.create
    step: "B6.1"
    SA: allow
    WA: {open: P2}
    BA: {allow_if: [own_branch]}
    FS: {allow_if: [own_branch]}
  - id: sale.list
    step: "B6.2"
    SA: allow
    WA: {open: P2}
    BA: {allow_if: [own_branch]}
    FS: {open: P10}
  - id: sale.read
    step: "B6.2"
    SA: allow
    WA: {open: P2}
    BA: {allow_if: [own_branch]}
    FS: {open: P10}
  - id: sale.cancel
    step: "B6.5"
    SA: allow
    WA: deny
    BA: {allow_if: [own_branch]}
    FS: deny
  - id: import.dry_run
    step: "B6.4"
    SA: allow
    WA: {open: P3}
    BA: {open: P3}
    FS: {open: P3}
  - id: import.commit
    step: "B6.4"
    SA: allow
    WA: {open: P3}
    BA: {open: P3}
    FS: {open: P3}
  - id: ledger.modify
    step: "B4.3"
    SA: deny
    WA: deny
    BA: deny
    FS: deny
  - id: audit.modify
    step: "B4.3"
    SA: deny
    WA: deny
    BA: deny
    FS: deny
  - id: stock.edit_balance_directly
    step: "B4.3"
    SA: deny
    WA: deny
    BA: deny
    FS: deny
```

## 9. Enforcement (summary; the design is in B2.4)

- DRF permission classes decide role, active branch and per-person permission per endpoint; the services re-check the same rules for every data-changing call (defence in depth). Views stay thin.
- The matrix above is the test oracle (SKILLS Testing Standards: every role against every protected endpoint; wrong branch refused; bad input returns the standard error).
- Rows `ledger.modify`, `audit.modify` and `stock.edit_balance_directly` are invariants: no endpoint exists, plus model and database level guards (ERD s7).

## 10. OPEN questions (owner)

None of these is decided by the documents. Each shows the matrix cells it blocks and a proposed default (only a proposal).

| Ref | Question | Blocks | Proposed default |
|---|---|---|---|
| P1 | Does a Super Admin select an active branch or location like other users (needed so a sale, receipt or stock list has a location)? | `context.select_branch`, `context.switch_branch` (SA) | Yes: any active location including the warehouse; each switch logged. |
| P2 | May a Warehouse Admin record or list sales? The docs list sell under Branch Admin and Front Staff only. | `sale.create`, `sale.list`, `sale.read` (WA) | No. |
| P3 | Who may run the CSV import, and may it load opening balances for branch locations or the warehouse only? BE s3.11 and B6.4 name no role. | `import.dry_run`, `import.commit` (WA, BA, FS) | SA and WA only; any location. |
| P4 | Do Branch Admin and Front Staff see Draft items, or Active only? | `item.read` | Active only. |
| P5 | Warehouse Admin creates items but only SA or a `manage_prices` holder sets prices (OQ-19). Who sets the first price? Must an item have a price to be activated or sold? | `item.activate`, `price.set` | Draft may lack a price; activation and sale require one; SA sets it or grants WA `manage_prices`. |
| P6 | Does `receive_stock` cover only receiving at a branch, not warehouse receipts (BE s4 says Warehouse Admin records receipts)? | `grn.create` (FS) | Yes, branch only; FS cannot create warehouse receipts. |
| P7 | May a Front Staff member without `receive_stock` see the list of dispatches waiting at the branch and their discrepancies read-only? | `dispatch.list_incoming`, `dispatch.read`, `discrepancy.read` (FS) | No: needs `receive_stock` to see waiting dispatches; may not see the discrepancy list. |
| P8 | "Within the branches it may act in" for a dispatch shortfall: the sender location, the destination, or either? | all `discrepancy.*` (WA, BA) | Either: the dispatch's origin or destination must be the caller's location. |
| P9 | May the person who recorded the receiving decision also resolve the resulting shortfall? | `discrepancy.resolve_*` | Yes (the rule bars only self-approval, which resolution is not). |
| P10 | Does Front Staff see the branch's whole sales list or only sales they recorded? | `sale.list`, `sale.read` (FS) | Own sales only. |
| P11 | Does the sale API accept any price override in Sprints 1-2 (BE s3.7: front staff cannot override "unless given that permission")? | `sale.create` | No: no price field; the price always comes from the price list. |
| P12 | Dashboard and activity log scope per role: what may WA, BA and FS see (the docs give the screens, not the scope)? | `dashboard.stats` (WA), `activity.list` (WA, BA, FS) | SA all; BA own branch; WA own location; FS no activity log. |
| P13 | May a Warehouse Admin see full stock figures of branch locations (not just the cross-branch lookup) to plan dispatches? | `stock.list_other_locations` (WA) | No: warehouse stock plus the lookup. |
| P14 | Does the cross-branch lookup list the warehouse location, and is the quantity shown "available" (on hand minus reserved)? | `stock.lookup_other_branches` | Branches only, available quantity. |
| P15 | May a Super Admin deactivate or demote themselves, or the last active Super Admin? | `user.set_status` (SA) | No. |
| P16 | May any per-person permission be granted to any role (section 3)? | `user.grant_permission` | Yes. |
| P17 | Can Front Staff pick the warehouse as a working location? | `context.list_selectable`, `context.select_branch` (FS) | No: branches only. |
| P18 | Login rate limit and lockout numbers (attempts, window, lockout length) for B2.3. The docs require a limit but give no numbers. | `auth.login` | 5 failed attempts per login ID and IP per 15 minutes, then a 15 minute lock; every attempt logged. |
| P19 | May a Branch Admin (or Super Admin) cancel a sale they recorded themselves? | `sale.cancel` | Yes, reason mandatory, audited. |

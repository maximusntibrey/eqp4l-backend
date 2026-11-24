# API contract

`openapi.yaml` is the published contract (OpenAPI 3.0.3, version 0.4.2), written first for the frontend (TASKS B1.3).

- This file is the published contract. From B2 onward the drf-spectacular generated schema must match it; the diff is checked in B5.6.
- Changes after publication need owner approval (SKILLS "API Development Standards"). Breaking changes only at a sprint boundary.
- Every operation has `x-permission`, taken from `docs/design/PERMISSION_TABLE.md`.
- Validated by `tests/test_openapi_contract.py` (schema validity, every path under `/api/v1/` or `/health/`, permission on every operation, Idempotency-Key on every state-changing operation except login, logout and password change, status enums match the SKILLS mapping, no cost field reachable by BA/FS).

## Changelog

### 0.4.2 (2026-11-24, owner-approved; FQ-11)
- `ActionPermission` gains `sales.cancel` (row 39: SA, BA) and `items.import` (rows 19, 20: SA, WA), so `/auth/me/` `permissions` tells the screens who may cancel and import. Sales entry (row 49): in `menu` for FS (5 items); in `home_links` for SA and BA, whose menus are already full. WA has no sales access.

### 0.4.1 (2026-11-24, owner-approved; OQ-31)
- New: `GET /costed-sales/` and `GET /costed-sales/{id}/` (SA only, table row 48): sale lines with `unit_cost` at 2 dp (the 4 dp snapshot rounded). Plain `/sales/` stays cost-free. New schema `CostedSale`.

### 0.4.0 (2026-11-24, owner-approved, Day 6; additive only, TASKS OQ-31..33)
- New: `GET/POST /sales/`, `GET /sales/{id}/`, `POST /sales/{id}/cancel/` (rows 36, 38, 39); `POST /item-imports/` (rows 19, 20, multipart, dry run). New schemas `Sale`, `SaleCreate`, `SaleCancel`, `SaleStatus`, `PaymentMethodCode`, `ItemImportRequest`, `ItemImportReport`; new tags `sales`, `imports`.
- Find (B6.3) needs no new operation: `/items/?q=`, `/stock/` and `/items/{id}/branch-availability/` already cover it.
- No published operation or schema changed. Sale payloads carry no cost (TASKS OQ-31).

### 0.3.2 (2026-11-24, owner-approved; OQ-30)

- `GET /dispatches/{id}/` and `POST /dispatches/{id}/receive/`: a dispatch to another branch is `404 not_found`, identical to a nonexistent id (no `403 wrong_branch` leak). `403` remains for roles or grants that may not read or receive. List behaviour unchanged.

### 0.3.1 (2026-11-24, owner-approved; Day 5)

- `GET /dispatches/` documents `400` (bad `status` or `destination_id`) and `403` (`wrong_branch`: BA and FS asking for another branch). No behaviour change.

### 0.3.0 (2026-11-24, owner-approved; Day 4)

- New read-only `GET /stock/movements/` (schemas `StockMovement`, `MovementType`): scoped like `/stock/`, newest first, filters `location_id`, `item_id`, `movement_type`, never carries cost.
- `ItemWithCostAndWarnings` warning code `duplicate_sku` removed: an exact SKU clash (any case) is 409 `conflict` on field `sku`. `duplicate_name_model` stays.
- `StockBalance` (and `StockBalanceWithCost`) gain `reorder_level` (nullable) and server-computed `low_stock` (reorder level set and available at or below it).
- `condition` query filter on `/items/` and `/costed-items/`.
- `400` documented on `/items/`, `/costed-items/`, `/stock/`, `/costed-stock/` list operations.
- `PATCH /items/{id}/` `key_specs` replaces the whole object (documented, behaviour unchanged).
- Selling-price permission is already in `/auth/me/` `permissions` as `prices.manage` (Super Admin, or a Manage prices holder).

### 0.2.0 (2026-11-24, owner-approved; Day 4)

- `/auth/me/` (and the working-branch response, same `Me` shape) gains required `all_branches` (true for Super Admin only).

### 0.1.2 (2026-11-24, owner-approved; published at the start of Day 3)
- New generic error code `conflict` (409) for any clash (duplicate stock post, code or name already in use, self status change). The stock service now answers `conflict` for a duplicate post; `idempotency_conflict` stays for an Idempotency-Key reused with a different body.
- `POST /api/v1/auth/password/` documents 429 `rate_limited` (5 wrong current passwords per 15 min per user); `TooManyRequests` reworded as generic.
- OQ-23: `ActionPermission` gains `sales.record` (Sell, row 36), `activity.view` (Activity, row 41), `find.use` (Find, rows 13 and 22) and `dashboard.view` (Home dashboard, row 40); Receive uses the existing `dispatches.receive`. PERMISSION_TABLE rows 44 to 47.
- `Me` gains `home_links` (Sell, Activity, Find, Receive Home tiles for Super Admin, new `MenuItem` schema, separate from the max-5 `menu`), `can_assign_multiple_roles` (true only for Super Admin) and `must_pick_branch` (true only when the role requires a working branch and none is chosen, i.e. Front Staff; always false for Super Admin, Branch Admin and Warehouse Admin). All three are required.
- Super Admin is never asked to pick a branch and works across all branches (owner, 2026-11-24): new optional query parameter `branch` (integer) on `GET /branches/`, `GET /users/` and `GET /dashboard/` views one branch; without it the Super Admin sees all branches. It is ignored for roles with a fixed location. The dashboard answers 400 for an unknown branch. `PUT /working-branch/` stays available to the Super Admin as an optional context (OQ-12) but is never required.
- Corrections found in B3: `GET /dashboard/` is SA, WA, BA only and returns 403 for Front Staff (table row 40; the contract said any logged-in user); `PUT /working-branch/` accepts only active locations of kind branch; `PUT /users/{id}/permissions/` allows `receive_stock` only for Front Staff users (table section 3). Documentation only, no shape change.

### 0.1.1 (2026-11-23, owner-approved)
- FIX-4: `Idempotency-Key` header on every state-changing operation except login, logout and password change (each also documents 400 and 409).
- FIX-5: status values are snake_case codes mapped 1:1 to the SKILLS words (mapping in each status schema description and ERD.md section 1). New account status `pending_activation`. Item status request values are now `active` / `discontinued`.
- OQ-20: `POST /api/v1/brands/`, `PATCH /api/v1/brands/{id}/` (SA, WA; `Brand.is_active`, new `BrandWrite`); image limit 5 MB JPEG/PNG/WebP and Discontinued final are documented.
- OQ-21: only SA or a Manage prices holder may send `selling_price` (403 otherwise); activation needs no price; sale blocked until a price exists.
- `GET /api/v1/working-branch/` is FS and SA only (table row 10); 403 added.
- Cost split: `Item` and `StockBalance` carry no cost. New SA/WA-only operations `GET /costed-items/`, `GET /costed-items/{id}/`, `GET /costed-stock/` return `ItemWithCost` and `StockBalanceWithCost`; item create, edit, status and image responses (SA, WA only) return the cost variants.
- `/users/{id}/status/` request accepts `active`, `suspended`, `deactivated` only (OQ-22 open).

### 0.1.0 (2026-11-23)
- First publication (B1.3).

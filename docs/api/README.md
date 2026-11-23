# API contract

`openapi.yaml` is the published contract (OpenAPI 3.0.3, version 0.1.1), written first for the frontend (TASKS B1.3).

- This file is the published contract. From B2 onward the drf-spectacular generated schema must match it; the diff is checked in B5.6.
- Changes after publication need owner approval (SKILLS "API Development Standards"). Breaking changes only at a sprint boundary.
- Every operation has `x-permission`, taken from `docs/design/PERMISSION_TABLE.md`.
- Validated by `tests/test_openapi_contract.py` (schema validity, every path under `/api/v1/` or `/health/`, permission on every operation, Idempotency-Key on every state-changing operation except login, logout and password change, status enums match the SKILLS mapping, no cost field reachable by BA/FS).

## Changelog

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

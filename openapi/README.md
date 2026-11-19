# API contract (B1.3)

`openapi.yaml` is the OpenAPI 3.1 contract for Sprints 1 and 2. It is **hand-authored and contract-first**: the backend implements against it (B2+), and the frontend builds its typed client and mock responses from it. It is the only link between the two repos (OVR s3).

Its sources are `docs/PERMISSIONS.md` (action IDs, roles, conditions) and `docs/ERD.md` (entities, types), both approved on 2026-11-19. Every operation carries:

- `x-action-id`: the PERMISSIONS action ID(s) it enforces (a list; `resolveDiscrepancy` lists the three resolve actions and `x-action-by-field` says which one `outcome` selects);
- `x-roles` and `x-conditions`: the roles that may ever call it and the matrix conditions per role (`own_branch`, `perm:receive_stock`, ...);
- `x-field-action-id`: `field.cost.read` on operations whose responses may carry cost;
- `x-open`: ids of open questions, listed once at the end of the file under `x-open`. Nothing the sources do not decide was invented: each such point is flagged there for the owner.

## Conventions

| Topic | Rule |
|---|---|
| URLs | `/api/v1/<plural-noun>/`; `/health/` is the only route outside the prefix. |
| Auth | Server-side session cookie. Unsafe methods (also login) need the `X-CSRFToken` header; `GET /api/v1/auth/session/` sets the cookie. |
| Lists | Paginated: `?page=&page_size=` (default 25, max 100), envelope `count, next, previous, results`. Bounded lists are plain arrays marked `x-unpaginated`. |
| Errors | One `Error` schema for every failure: `code`, plain `message`, and `errors[]` of `field`, `code`, `message`. 400 field errors, 401 not signed in, 403 not allowed, 404 record not found or outside the caller's scope, 409 state conflict, 429 login lock. |
| Money | Decimal string, exactly 2 dp, GHS: `"1250.00"`. Never a JSON number. |
| Quantities | Decimal string, `numeric(12,3)`: responses always 3 dp (`"12.000"`), requests up to 3 dp. |
| Time | UTC, RFC 3339 with `Z`. The frontend shows Africa/Accra. |
| Idempotency | `Idempotency-Key: <uuid>` header on every stock-changing POST (receipt, dispatch, receiving decision, resolution, sale, cancel, import commit). A replay returns the original result; a different body with the same key is 409. |
| Cost | `average_cost` and `unit_cost` carry `x-visible-to: [super_admin, warehouse_admin]`. For Branch Admin and Front Staff the property is **absent** (not null, not masked). |
| Menus and forms | `GET /auth/me/` returns the role, active branch, `allowed_actions` and `menu`; objects carry their own `allowed_actions`; `GET /item-field-definitions/` returns the item form; error messages come from `Error`. The frontend hard-codes none of it. |

## How the frontend consumes it

Generate types from the file (`openapi-typescript`, task T.20 / F1.4):

```
npx openapi-typescript ../eqp4l-backend/openapi/openapi.yaml -o src/api/schema.d.ts
```

Mock responses (MSW) follow the same file. Do not hand-write request or response types.

## Checking it

```
python scripts/validate_openapi.py
```

runs inside `bash scripts/check.sh` and in CI. It validates the document with PyYAML and `jsonschema` (already in the stack) and enforces the rules above, including that `x-action-id`, `x-roles` and `x-conditions` match the machine-readable matrix in `docs/PERMISSIONS.md` and that every action has an endpoint (except the invariant rows 53-55, which must have none). It is covered by `tests/test_openapi_contract.py`.

## Changing it

After B1.3 merges, a change is a contract change (TASKS 0.2): propose, agree with the owner, update this file, then both sides adjust. Breaking changes only at a sprint boundary. Never mix a contract change with an unrelated fix.

## drf-spectacular

The views will publish their own schema with drf-spectacular (`SPECTACULAR_SETTINGS`, version `0.1.0`). Once the endpoints exist, the generated output **must be diffed against this file** in CI, and any difference is fixed in the code or proposed as a contract change. That check is not added yet: there is nothing to generate until B2+ builds the views (add it in the first step that serves `/api/v1/` endpoints).

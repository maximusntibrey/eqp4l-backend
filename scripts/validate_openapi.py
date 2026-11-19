"""Validate the hand-authored API contract, openapi/openapi.yaml (TASKS B1.3).

    python scripts/validate_openapi.py            # exits non-zero and lists every problem

Uses only tools already in the vetted stack (PyYAML and jsonschema, both pinned in
requirements/base.txt): no OpenAPI validator package was added. It checks

* the document shape (OpenAPI 3.1, info, paths, operations, responses, security names);
* that every ``$ref`` resolves, and every component schema is used;
* that every Schema Object is a valid JSON Schema (draft 2020-12, the dialect of OpenAPI 3.1);
* the project rules: no floating point numbers, money and quantity and timestamp fields use the
  shared string types, cost fields are visible to Super Admin and Warehouse Admin only, every
  stock-changing POST takes the Idempotency-Key header, lists are paginated or marked bounded,
  every protected operation documents 401 and 403;
* that ``x-action-id``, ``x-roles`` and ``x-conditions`` of every operation agree with the
  machine-readable matrix in docs/PERMISSIONS.md (section 8.2), and that every action of the
  matrix has an endpoint, except the invariant rows that must have none.

Later, drf-spectacular output is diffed against this file once the endpoints exist (see
openapi/README.md).
"""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator  # type: ignore[import-untyped]
from jsonschema.exceptions import SchemaError  # type: ignore[import-untyped]

ROOT = Path(__file__).resolve().parent.parent
SPEC_PATH = ROOT / "openapi" / "openapi.yaml"
PERMISSIONS_PATH = ROOT / "docs" / "PERMISSIONS.md"

ROLE_CODES = {
    "SA": "super_admin",
    "WA": "warehouse_admin",
    "BA": "branch_admin",
    "FS": "front_staff",
}
# Rows with no endpoint by design (PERMISSIONS 53-55), and the field-level rule (row 29).
NO_ENDPOINT = {"ledger.modify", "audit.modify", "stock.edit_balance_directly"}
FIELD_RULE = {"field.cost.read"}
COST_VISIBLE_TO = ["super_admin", "warehouse_admin"]
IDEMPOTENT_ACTIONS = {
    "grn.create",
    "dispatch.create",
    "dispatch.receive",
    "discrepancy.resolve_return",
    "discrepancy.resolve_loss",
    "discrepancy.resolve_damage",
    "sale.create",
    "sale.cancel",
    "import.commit",
}
HTTP_METHODS = {"get", "put", "post", "delete", "options", "head", "patch", "trace"}
MONEY_KEY = re.compile(r"(^|_)(amount|total|price|cost)$")
QUANTITY_KEY = re.compile(
    r"^(qty_\w+|quantity|quantity_\w+|available|available_here|on_hand|reserved|quarantined"
    r"|reorder_level|\w+_quantity)$"
)
TIMESTAMP_KEY = re.compile(r"_at$")


def load_matrix(path: Path = PERMISSIONS_PATH) -> dict[str, dict[str, Any]]:
    """Read the machine-readable permission matrix (section 8.2) out of PERMISSIONS.md."""
    text = path.read_text(encoding="utf-8")
    match = re.search(r"### 8\.2.*?```yaml\n(.*?)```", text, re.S)
    if match is None:
        raise ValueError("section 8.2 yaml block not found in PERMISSIONS.md")
    actions = yaml.safe_load(match.group(1))["actions"]
    return {a["id"]: a for a in actions}


def expected_roles(matrix: dict[str, dict[str, Any]], ids: list[str]) -> list[str]:
    roles = []
    for short, code in ROLE_CODES.items():
        if any(matrix[i][short] != "deny" for i in ids):
            roles.append(code)
    return roles


def expected_conditions(
    matrix: dict[str, dict[str, Any]], ids: list[str]
) -> dict[str, dict[str, list[str]]]:
    out: dict[str, dict[str, list[str]]] = {}
    for i in ids:
        per_role = {
            code: list(matrix[i][short]["allow_if"])
            for short, code in ROLE_CODES.items()
            if isinstance(matrix[i][short], dict)
        }
        if per_role:
            out[i] = per_role
    return out


def _walk(node: Any, path: str = "#") -> Iterator[tuple[str, Any]]:
    """Yield (path, node) for every dict and list in the document."""
    yield path, node
    if isinstance(node, dict):
        for key, value in node.items():
            yield from _walk(value, f"{path}/{key}")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _walk(value, f"{path}/{index}")


def _resolve(spec: dict[str, Any], ref: str) -> Any:
    if not ref.startswith("#/"):
        raise KeyError(ref)
    node: Any = spec
    for part in ref[2:].split("/"):
        node = node[part.replace("~1", "/").replace("~0", "~")]
    return node


def _schema_nodes(spec: dict[str, Any]) -> Iterator[tuple[str, Any]]:
    """Yield (location, schema) for every Schema Object that sits under a ``schema`` key or in
    components.schemas (nested schemas are checked as part of their parent)."""
    for name, schema in spec.get("components", {}).get("schemas", {}).items():
        yield f"components.schemas.{name}", schema
    for loc, node in _walk(spec):
        if (
            isinstance(node, dict)
            and "schema" in node
            and not loc.startswith("#/components/schemas")
            and isinstance(node["schema"], dict)
        ):
            yield f"{loc}/schema", node["schema"]


def _properties(node: Any, loc: str) -> Iterator[tuple[str, str, Any]]:
    """Yield (location, key, property schema) for every ``properties`` entry below node."""
    for sub_loc, sub in _walk(node, loc):
        if isinstance(sub, dict) and isinstance(sub.get("properties"), dict):
            for key, value in sub["properties"].items():
                yield f"{sub_loc}/properties/{key}", key, value


def _response_cost_fields(spec: dict[str, Any], op: dict[str, Any]) -> list[tuple[str, bool]]:
    """Cost properties (carrying x-visible-to) reachable from the success responses of an
    operation, as (name, required-in-its-parent). Follows $ref, arrays, allOf/oneOf and inline
    schemas transitively."""
    found: list[tuple[str, bool]] = []
    seen: set[str] = set()

    def visit(node: Any) -> None:
        if isinstance(node, list):
            for value in node:
                visit(value)
            return
        if not isinstance(node, dict):
            return
        ref = node.get("$ref")
        if isinstance(ref, str):
            if ref not in seen:
                seen.add(ref)
                try:
                    target = _resolve(spec, ref)
                except (KeyError, TypeError):
                    return  # reported as an unresolved $ref elsewhere
                visit(target)
            return
        props = node.get("properties")
        if isinstance(props, dict):
            required = node.get("required", [])
            for key, value in props.items():
                if "cost" in key.lower() and isinstance(value, dict) and "x-visible-to" in value:
                    found.append((key, key in required))
        for key, value in node.items():
            if key not in ("example", "examples"):
                visit(value)

    for code, response in op.get("responses", {}).items():
        if str(code).startswith("2"):
            visit(response)
    return found


def validate(spec: dict[str, Any], matrix: dict[str, dict[str, Any]]) -> list[str]:
    errors: list[str] = []

    def err(msg: str) -> None:
        errors.append(msg)

    # --- document shape -------------------------------------------------------------
    if not str(spec.get("openapi", "")).startswith("3.1"):
        err("openapi must be a 3.1.x version")
    info = spec.get("info", {})
    for key in ("title", "version"):
        if not info.get(key):
            err(f"info.{key} is required")
    paths: dict[str, Any] = spec.get("paths", {})
    if not paths:
        err("paths is empty")
    components = spec.get("components", {})
    schemas: dict[str, Any] = components.get("schemas", {})
    security_schemes = set(components.get("securitySchemes", {}))
    tag_names = {t["name"] for t in spec.get("tags", [])}
    open_ids = {o["id"] for o in spec.get("x-open", [])}

    # --- references -----------------------------------------------------------------
    used_schemas: set[str] = set()
    for loc, node in _walk(spec):
        if isinstance(node, dict) and "$ref" in node:
            ref = node["$ref"]
            try:
                _resolve(spec, ref)
            except (KeyError, TypeError):
                err(f"{loc}: unresolved $ref {ref}")
                continue
            if ref.startswith("#/components/schemas/"):
                used_schemas.add(ref.rsplit("/", 1)[1])
    for name in sorted(set(schemas) - used_schemas):
        err(f"components.schemas.{name} is never used")

    # --- JSON Schema validity (draft 2020-12) ---------------------------------------
    for loc, schema in _schema_nodes(spec):
        try:
            Draft202012Validator.check_schema(schema)
        except SchemaError as exc:
            err(f"{loc}: invalid schema: {exc.message}")

    # --- type rules -------------------------------------------------------------------
    for loc, node in _walk(spec):
        if isinstance(node, dict) and node.get("type") == "number":
            err(f"{loc}: floating point 'number' is forbidden; money and quantities are strings")
    for name in ("Money", "Quantity", "QuantityInput", "Timestamp"):
        if schemas.get(name, {}).get("type") != "string":
            err(f"components.schemas.{name} must be a string type")

    for loc, key, prop in _properties(schemas, "components.schemas"):
        dumped = json.dumps(prop)
        if MONEY_KEY.search(key) and "Money" not in dumped:
            err(f"{loc}: money field must use the shared Money schema")
        if QUANTITY_KEY.match(key) and "Quantity" not in dumped:
            err(f"{loc}: quantity field must use the shared Quantity schema")
        if TIMESTAMP_KEY.search(key) and "Timestamp" not in dumped:
            err(f"{loc}: timestamp field must use the shared Timestamp schema")
    for loc, key, prop in _properties(spec, "#"):
        if "cost" in key.lower() and prop.get("x-visible-to") != COST_VISIBLE_TO:
            err(f"{loc}: cost field must carry x-visible-to {COST_VISIBLE_TO}")
    for loc, _key, prop in _properties(spec, "#"):
        if "x-visible-to" in prop and not set(prop["x-visible-to"]) <= set(ROLE_CODES.values()):
            err(f"{loc}: x-visible-to has an unknown role")
    for key in ("Error", "ErrorDetail", "PageEnvelope"):
        if key not in schemas:
            err(f"components.schemas.{key} is required (shared error and pagination types)")

    # --- operations -------------------------------------------------------------------
    operation_ids: set[str] = set()
    covered: set[str] = set()
    field_covered: set[str] = set()
    n_ops = 0
    for path, item in paths.items():
        if not path.startswith("/"):
            err(f"{path}: path must start with /")
        if path != "/health/" and not path.startswith("/api/v1/"):
            err(f"{path}: must be under /api/v1/ (only /health/ is outside)")
        for method, op in item.items():
            if method not in HTTP_METHODS:
                continue
            n_ops += 1
            where = f"{method.upper()} {path}"
            oid = op.get("operationId")
            if not oid:
                err(f"{where}: operationId is required")
            elif oid in operation_ids:
                err(f"{where}: duplicate operationId {oid}")
            else:
                operation_ids.add(oid)
            for tag in op.get("tags", []):
                if tag not in tag_names:
                    err(f"{where}: tag {tag} is not declared")
            if not op.get("summary"):
                err(f"{where}: summary is required")

            # permissions
            ids = op.get("x-action-id")
            public = bool(op.get("x-public"))
            if not isinstance(ids, list):
                err(f"{where}: x-action-id (a list) is required")
                ids = []
            if not ids and not public:
                err(f"{where}: no x-action-id and not marked x-public")
            if ids and public and ids != ["auth.login"]:
                err(f"{where}: x-public operations carry no action ID (except auth.login)")
            for action in ids:
                if action not in matrix:
                    err(f"{where}: unknown action ID {action}")
                elif action in NO_ENDPOINT | FIELD_RULE:
                    err(f"{where}: {action} must have no endpoint")
            known = [a for a in ids if a in matrix]
            covered.update(known)
            if known:
                if op.get("x-roles") != expected_roles(matrix, known):
                    err(f"{where}: x-roles {op.get('x-roles')} differs from PERMISSIONS.md")
                if op.get("x-conditions", {}) != expected_conditions(matrix, known):
                    err(f"{where}: x-conditions differs from PERMISSIONS.md")
            for action in op.get("x-field-action-id", []):
                if action not in FIELD_RULE:
                    err(f"{where}: x-field-action-id may only hold {sorted(FIELD_RULE)}")
                field_covered.add(action)
            for ref_id in op.get("x-open", []):
                if ref_id not in open_ids:
                    err(f"{where}: x-open {ref_id} is not listed in the top-level x-open")

            # cost in responses, followed through $ref, arrays and inline schemas
            reached = _response_cost_fields(spec, op)
            has_field_action = "field.cost.read" in op.get("x-field-action-id", [])
            if reached and not has_field_action:
                err(
                    f"{where}: a response reaches cost field {reached[0][0]} but the operation "
                    "has no x-field-action-id field.cost.read"
                )
            if has_field_action and not reached:
                err(f"{where}: x-field-action-id field.cost.read but no response has a cost field")
            roles = set(op.get("x-roles", []))
            if any(required for _name, required in reached) and not roles <= set(COST_VISIBLE_TO):
                err(f"{where}: required cost field, but roles that must not see cost may call this")

            # security
            security = op.get("security", spec.get("security", []))
            for requirement in security:
                for scheme in requirement:
                    if scheme not in security_schemes:
                        err(f"{where}: unknown security scheme {scheme}")
            unsafe = method in ("post", "put", "patch", "delete")
            if unsafe and not any("csrfToken" in r for r in security):
                err(f"{where}: unsafe method must require the csrfToken scheme")
            if not public and not any("sessionCookie" in r for r in security):
                err(f"{where}: protected operation must require sessionCookie")

            # path parameters
            resolved = [
                _resolve(spec, p["$ref"]) if "$ref" in p else p for p in op.get("parameters", [])
            ]
            path_params = {p["name"] for p in resolved if p["in"] == "path"}
            in_url = set(re.findall(r"{(\w+)}", path))
            if path_params != in_url:
                err(f"{where}: path parameters {sorted(path_params)} differ from the URL")
            for p in resolved:
                if p["in"] == "path" and p.get("required") is not True:
                    err(f"{where}: path parameter {p['name']} must be required")
            names = {(p["name"], p["in"]) for p in resolved}

            # idempotency
            needs_key = method == "post" and bool(set(known) & IDEMPOTENT_ACTIONS)
            has_key = ("Idempotency-Key", "header") in names
            if needs_key != has_key:
                err(f"{where}: Idempotency-Key is needed on stock-changing POSTs only")

            # responses
            responses = op.get("responses", {})
            if not responses:
                err(f"{where}: responses are required")
            for code in responses:
                if not re.fullmatch(r"[1-5]\d\d", str(code)):
                    err(f"{where}: bad response code {code}")
            if not any(str(c).startswith("2") for c in responses):
                err(f"{where}: needs a 2xx response")
            if not public:
                for code in ("401", "403"):
                    if code not in responses:
                        err(f"{where}: protected operation must document {code}")
            if path_params and "404" not in responses:
                err(f"{where}: operation with an id in the URL must document 404")
            if op.get("requestBody") and "400" not in responses:
                err(f"{where}: operation with a body must document 400")
            if needs_key and "409" not in responses:
                err(f"{where}: idempotent operation must document 409")
            if needs_key:
                ok_code = next((c for c in responses if str(c).startswith("2")), None)
                headers = responses.get(ok_code, {}).get("headers", {}) if ok_code else {}
                if "Idempotent-Replayed" not in headers:
                    err(f"{where}: idempotent operation needs the Idempotent-Replayed header")
            for code, response in responses.items():
                if "$ref" in response:
                    continue
                if (
                    str(code) not in ("204",)
                    and "content" not in response
                    and not str(code).startswith("2")
                ):
                    err(f"{where}: response {code} has no content")
            # error bodies must use the shared Error schema
            for code in ("400", "401", "403", "404", "409", "429"):
                response = responses.get(code)
                if not response:
                    continue
                if "$ref" in response:
                    response = _resolve(spec, response["$ref"])
                body = response.get("content", {}).get("application/json", {}).get("schema")
                if body != {"$ref": "#/components/schemas/Error"}:
                    err(f"{where}: {code} must use the shared Error schema")

            # pagination
            if method == "get":
                ok = next((c for c in responses if str(c).startswith("2")), None)
                content = responses[ok].get("content", {}) if ok else {}
                schema = content.get("application/json", {}).get("schema", {})
                ref = schema.get("$ref", "")
                is_page = ref.endswith("Page")
                is_array = schema.get("type") == "array"
                if is_page and not {("page", "query"), ("page_size", "query")} <= names:
                    err(f"{where}: paginated list must take page and page_size")
                if is_array and not op.get("x-unpaginated"):
                    err(f"{where}: array response must be paginated or marked x-unpaginated")
                if op.get("x-unpaginated") and not is_array:
                    err(f"{where}: x-unpaginated only applies to array responses")

    # --- coverage of the matrix ---------------------------------------------------------
    for action in matrix:
        if action in NO_ENDPOINT:
            if action in covered:
                err(f"{action} must have no endpoint")
        elif action in FIELD_RULE:
            if action not in field_covered:
                err(f"{action} is not referenced by any operation returning cost")
        elif action not in covered:
            err(f"action {action} has no endpoint in the contract")
    if n_ops == 0:
        err("no operations")
    return errors


def main() -> int:
    spec = yaml.safe_load(SPEC_PATH.read_text(encoding="utf-8"))
    matrix = load_matrix()
    errors = validate(spec, matrix)
    if errors:
        print(f"openapi/openapi.yaml: {len(errors)} problem(s)")
        for message in errors:
            print(f"  - {message}")
        return 1
    n_ops = sum(1 for item in spec["paths"].values() for method in item if method in HTTP_METHODS)
    print(
        f"openapi/openapi.yaml OK: {len(spec['paths'])} paths, {n_ops} operations, "
        f"{len(spec['components']['schemas'])} schemas, {len(matrix)} permission rows checked"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

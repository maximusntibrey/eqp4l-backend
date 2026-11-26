"""B1.3: the published contract (docs/api/openapi.yaml) is valid and follows the house rules."""

import re
from pathlib import Path
from typing import Any

import pytest
import yaml
from drf_spectacular.validation import validate_schema

CONTRACT = Path(__file__).resolve().parent.parent / "docs" / "api" / "openapi.yaml"
METHODS = {"get", "post", "put", "patch", "delete"}
ROOT = CONTRACT.parent.parent.parent
# FIX-4: every state-changing operation needs the key except these three.
NO_KEY = {
    ("/api/v1/auth/login/", "post"),
    ("/api/v1/auth/logout/", "post"),
    ("/api/v1/auth/password/", "post"),
}
# FIX-5: status code per SKILLS status word, 1:1 (MVP subset for Transfer).
STATUS_MAP = {
    "UserStatus": {
        "Active": "active",
        "Pending activation": "pending_activation",
        "Suspended": "suspended",
        "Deactivated": "deactivated",
    },
    "ItemStatus": {"Draft": "draft", "Active": "active", "Discontinued": "discontinued"},
    "DispatchStatus": {
        "In transit": "in_transit",
        "Completed": "completed",
        "Partially received": "partially_received",
        "Rejected": "rejected",
    },
}
# ERD table to schema for `text status "..."` lines.
ERD_STATUS = {"users": "UserStatus", "items": "ItemStatus", "dispatches": "DispatchStatus"}


@pytest.fixture(scope="module")
def spec() -> dict[str, Any]:
    loaded: dict[str, Any] = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))
    return loaded


def operations(spec: dict[str, Any]) -> list[tuple[str, str, dict[str, Any]]]:
    return [(p, m, op) for p, item in spec["paths"].items() for m, op in item.items() if m in METHODS]


def test_contract_is_valid_openapi(spec: dict[str, Any]) -> None:
    validate_schema(spec)
    assert spec["openapi"].startswith("3.")
    assert spec["info"]["version"] == "0.6.0"


def test_every_path_is_versioned_or_health(spec: dict[str, Any]) -> None:
    bad = [p for p in spec["paths"] if not (p.startswith("/api/v1/") or p == "/health/")]
    assert bad == []


def test_every_operation_declares_permission_and_unique_id(spec: dict[str, Any]) -> None:
    ops = operations(spec)
    assert all(op.get("x-permission") for _, _, op in ops)
    ids = [op["operationId"] for _, _, op in ops]
    assert len(ids) == len(set(ids))


def test_idempotency_key_on_every_state_changing_op(spec: dict[str, Any]) -> None:
    count = 0
    for path, method, op in operations(spec):
        refs = [p.get("$ref", "") for p in op.get("parameters", [])]
        has_key = any(r.endswith("/IdempotencyKey") for r in refs)
        needs_key = method != "get" and (path, method) not in NO_KEY
        assert has_key == needs_key, (path, method)
        if needs_key:
            count += 1
            assert {"400", "409"} <= set(op["responses"]), (path, method)  # bad key, key conflict
    assert count == 23  # guards against an op silently dropping out of the check


def test_status_enums_match_mapping(spec: dict[str, Any]) -> None:
    schemas = spec["components"]["schemas"]
    for name, mapping in STATUS_MAP.items():
        assert schemas[name]["enum"] == list(mapping.values()), name
        for word, code in mapping.items():  # mapping documented in the schema description
            assert f"`{code}` = {word}" in " ".join(schemas[name]["description"].split()), (name, code)
    allowed = {c for m in STATUS_MAP.values() for c in m.values()}
    for path, method, op in operations(spec):  # inline status enums are subsets of the mapping
        body = op.get("requestBody", {}).get("content", {}).get("application/json", {}).get("schema", {})
        inline = body.get("properties", {}).get("status", {}).get("enum", [])
        assert set(inline) <= allowed, (path, method)


def test_erd_status_codes_match_mapping(spec: dict[str, Any]) -> None:
    erd = (ROOT / "docs" / "design" / "ERD.md").read_text(encoding="utf-8")
    table = ""
    found: dict[str, list[str]] = {}
    for line in erd.splitlines():
        if line.strip().endswith("{") and line.startswith("    ") and "||" not in line:
            table = line.split()[0]
        m = re.match(r'\s+text status "([^"]+)"', line)
        if m and table in ERD_STATUS:
            found[table] = m.group(1).split(", ")
    for table, schema in ERD_STATUS.items():
        assert found[table] == list(STATUS_MAP[schema].values()), table
    assert "pending_activation" in erd


def test_brand_endpoints_and_price_rule_documented(spec: dict[str, Any]) -> None:
    paths = spec["paths"]
    assert "post" in paths["/api/v1/brands/"]
    assert "patch" in paths["/api/v1/brands/{id}/"]
    for op in (paths["/api/v1/brands/"]["post"], paths["/api/v1/brands/{id}/"]["patch"]):
        assert op["x-permission"].startswith("SA, WA")
    assert "is_active" in spec["components"]["schemas"]["Brand"]["properties"]
    for op in (paths["/api/v1/items/"]["post"], paths["/api/v1/items/{id}/"]["patch"]):
        assert "403" in op["responses"] and "manage_prices" in op["x-permission"]
    assert paths["/api/v1/working-branch/"]["get"]["x-permission"].startswith("FS, SA")


def test_v012_changes(spec: dict[str, Any]) -> None:
    schemas, responses = spec["components"]["schemas"], spec["components"]["responses"]
    assert "`conflict`" in responses["Conflict"]["description"]
    assert "429" in spec["paths"]["/api/v1/auth/password/"]["post"]["responses"]
    assert "Login rate limit" not in responses["TooManyRequests"]["description"]
    assert {"sales.record", "activity.view", "find.use", "dashboard.view", "dispatches.receive"} <= set(
        schemas["ActionPermission"]["enum"]
    )
    me = schemas["Me"]
    assert {"must_pick_branch", "can_assign_multiple_roles", "home_links"} <= set(me["required"])
    assert set(schemas["MenuItem"]["properties"]) == {"key", "label", "path"}
    assert "placement" not in str(me)
    for path in ("/api/v1/branches/", "/api/v1/users/", "/api/v1/dashboard/"):  # SA all-branch view filter
        refs = [p.get("$ref", "") for p in spec["paths"][path]["get"]["parameters"]]
        assert "#/components/parameters/BranchFilter" in refs, path
    assert "403" in spec["paths"]["/api/v1/dashboard/"]["get"]["responses"]


def test_all_refs_resolve(spec: dict[str, Any]) -> None:
    def walk(node: Any) -> list[str]:
        if isinstance(node, dict):
            found = [node["$ref"]] if isinstance(node.get("$ref"), str) else []
            return found + [r for v in node.values() for r in walk(v)]
        if isinstance(node, list):
            return [r for v in node for r in walk(v)]
        return []

    for ref in walk(spec):
        target: Any = spec
        for part in ref.removeprefix("#/").split("/"):
            target = target[part]


def test_cost_never_in_required_fields(spec: dict[str, Any]) -> None:
    for name in ("Item", "StockBalance"):
        assert "average_cost" not in spec["components"]["schemas"][name]["properties"]
    for name in ("ItemWithCost", "StockBalanceWithCost"):
        assert "average_cost" in spec["components"]["schemas"][name]["allOf"][1]["properties"]

"""The hand-authored API contract (B1.3) and its validator (scripts/validate_openapi.py).

The contract is the frontend's only source (OVR s3), so these tests pin the rules that must
never drift: permission IDs and roles agree with docs/PERMISSIONS.md, cost never leaks to
Branch Admin or Front Staff, stock-changing POSTs take an Idempotency-Key, the cross-branch
lookup returns branch name and quantity only, and the validator really rejects bad contracts.
"""

from __future__ import annotations

import copy
import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent


def _load_validator() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "validate_openapi", ROOT / "scripts" / "validate_openapi.py"
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["validate_openapi"] = module
    spec.loader.exec_module(module)
    return module


validator = _load_validator()
MATRIX = validator.load_matrix()


def _spec() -> dict[str, Any]:
    loaded: dict[str, Any] = yaml.safe_load(
        (ROOT / "openapi" / "openapi.yaml").read_text(encoding="utf-8")
    )
    return loaded


def _problems(spec: dict[str, Any]) -> list[str]:
    result: list[str] = validator.validate(spec, MATRIX)
    return result


def _op(spec: dict[str, Any], method: str, path: str) -> dict[str, Any]:
    op: dict[str, Any] = spec["paths"][path][method]
    return op


# --- the committed contract --------------------------------------------------------


def test_contract_is_valid() -> None:
    assert _problems(_spec()) == []


def test_every_permission_row_has_an_endpoint_except_the_invariants() -> None:
    spec = _spec()
    seen = {
        action
        for item in spec["paths"].values()
        for op in item.values()
        for action in op.get("x-action-id", [])
    }
    expected = set(MATRIX) - validator.NO_ENDPOINT - validator.FIELD_RULE
    assert expected <= seen
    assert not seen & validator.NO_ENDPOINT


def test_cross_branch_lookup_exposes_branch_name_and_quantity_only() -> None:
    schema = _spec()["components"]["schemas"]["OtherBranchStock"]
    assert set(schema["properties"]) == {"branch_name", "available"}
    assert schema["additionalProperties"] is False


def test_cost_fields_are_never_required_and_only_for_cost_roles() -> None:
    schemas = _spec()["components"]["schemas"]
    for name in ("Item", "GoodsReceiptLine"):
        prop_name = "average_cost" if name == "Item" else "unit_cost"
        prop = schemas[name]["properties"][prop_name]
        assert prop["x-visible-to"] == ["super_admin", "warehouse_admin"]
    assert "average_cost" not in schemas["Item"]["required"]
    # No other response schema carries a cost property.
    for name, schema in schemas.items():
        if name in {"Item", "GoodsReceiptLine", "GoodsReceiptLineCreate"}:
            continue
        assert not [k for k in schema.get("properties", {}) if "cost" in k], name


def test_sale_body_accepts_no_price_or_discount() -> None:
    schema = _spec()["components"]["schemas"]["SaleCreate"]
    assert schema["additionalProperties"] is False
    assert set(schema["properties"]) == {"payment_method", "lines"}
    line = _spec()["components"]["schemas"]["SaleLineCreate"]
    assert set(line["properties"]) == {"item", "quantity"}


def test_goods_receipts_are_visible_to_cost_roles_only() -> None:
    spec = _spec()
    for method, path in (
        ("post", "/api/v1/goods-receipts/"),
        ("get", "/api/v1/goods-receipts/"),
        ("get", "/api/v1/goods-receipts/{receipt_id}/"),
    ):
        assert _op(spec, method, path)["x-roles"] == ["super_admin", "warehouse_admin"]


def test_health_is_public_and_outside_the_api_prefix() -> None:
    op = _op(_spec(), "get", "/health/")
    assert op["security"] == []
    assert "401" not in op["responses"]


# --- the validator rejects bad contracts -----------------------------------------------


def _mutations() -> dict[str, Any]:
    def drop_action_id(s: dict[str, Any]) -> None:
        del _op(s, "get", "/api/v1/items/")["x-action-id"]

    def add_float(s: dict[str, Any]) -> None:
        s["components"]["schemas"]["PriceSet"]["properties"]["amount"] = {"type": "number"}

    def leak_cost(s: dict[str, Any]) -> None:
        del s["components"]["schemas"]["Item"]["properties"]["average_cost"]["x-visible-to"]

    def drop_idempotency(s: dict[str, Any]) -> None:
        op = _op(s, "post", "/api/v1/sales/")
        op["parameters"] = [p for p in op["parameters"] if "IdempotencyKey" not in p["$ref"]]

    def wrong_roles(s: dict[str, Any]) -> None:
        _op(s, "post", "/api/v1/sales/")["x-roles"].append("warehouse_admin")

    def broken_ref(s: dict[str, Any]) -> None:
        s["components"]["schemas"]["Branch"]["properties"]["kind"] = {
            "$ref": "#/components/schemas/Nope"
        }

    def invariant_endpoint(s: dict[str, Any]) -> None:
        _op(s, "get", "/api/v1/prices/")["x-action-id"].append("ledger.modify")

    def drop_403(s: dict[str, Any]) -> None:
        del _op(s, "get", "/api/v1/users/")["responses"]["403"]

    def unpaginated_list(s: dict[str, Any]) -> None:
        _op(s, "get", "/api/v1/branches/")["responses"]["200"]["content"]["application/json"][
            "schema"
        ] = {"type": "array", "items": {"$ref": "#/components/schemas/Branch"}}

    def bad_schema(s: dict[str, Any]) -> None:
        s["components"]["schemas"]["Id"]["minimum"] = "one"

    def money_as_string(s: dict[str, Any]) -> None:
        s["components"]["schemas"]["Sale"]["properties"]["total"] = {"type": "string"}

    def missing_endpoint(s: dict[str, Any]) -> None:
        del s["paths"]["/api/v1/sales/{sale_id}/cancel/"]

    def old_openapi(s: dict[str, Any]) -> None:
        s["openapi"] = "3.0.3"

    return {
        "no action id": drop_action_id,
        "float": add_float,
        "cost leak": leak_cost,
        "no idempotency": drop_idempotency,
        "wrong roles": wrong_roles,
        "broken ref": broken_ref,
        "invariant endpoint": invariant_endpoint,
        "no 403": drop_403,
        "unpaginated list": unpaginated_list,
        "bad schema": bad_schema,
        "money not shared": money_as_string,
        "missing endpoint": missing_endpoint,
        "wrong version": old_openapi,
    }


@pytest.mark.parametrize("name", list(_mutations()))
def test_validator_rejects(name: str) -> None:
    spec = copy.deepcopy(_spec())
    _mutations()[name](spec)
    assert _problems(spec), f"validator accepted a contract with: {name}"

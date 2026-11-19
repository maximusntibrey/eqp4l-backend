"""The hand-authored API contract (B1.3) and its validator (scripts/validate_openapi.py).

The contract is the frontend's only source (OVR s3), so these tests pin the rules that must
never drift: permission IDs and roles agree with docs/PERMISSIONS.md, cost never leaks to
Branch Admin or Front Staff, stock-changing POSTs take an Idempotency-Key, the cross-branch
lookup returns branch name and quantity only, and the validator really rejects bad contracts.
"""

from __future__ import annotations

import copy
import importlib.util
import re
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import yaml
from jsonschema import Draft202012Validator  # type: ignore[import-untyped]

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
        if name in {"Item", "GoodsReceiptLine", "GoodsReceiptLineCreate", "ImportPreviewRow"}:
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


# --- contract details the reviewer pinned --------------------------------------------


def _schemas() -> dict[str, Any]:
    schemas: dict[str, Any] = _spec()["components"]["schemas"]
    return schemas


def test_average_cost_is_nullable_money_for_cost_roles_only() -> None:
    prop = _schemas()["Item"]["properties"]["average_cost"]
    assert {"$ref": "#/components/schemas/Money"} in prop["oneOf"]
    assert {"type": "null"} in prop["oneOf"]
    assert prop["x-visible-to"] == ["super_admin", "warehouse_admin"]


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("post", "/api/v1/sales/"),
        ("post", "/api/v1/dispatches/"),
        ("post", "/api/v1/dispatches/{dispatch_id}/receive/"),
        ("post", "/api/v1/discrepancies/{discrepancy_id}/resolutions/"),
    ],
)
def test_insufficient_stock_is_409_everywhere(method: str, path: str) -> None:
    assert "409" in _op(_spec(), method, path)["responses"]


def test_400_example_is_not_a_stock_error_and_409_has_one() -> None:
    responses = _spec()["components"]["responses"]
    bad = responses["ValidationError"]["content"]["application/json"]["example"]
    assert all(e["code"] != "insufficient_stock" for e in bad["errors"])
    examples = responses["Conflict"]["content"]["application/json"]["examples"]
    assert examples["insufficient_stock"]["value"]["errors"][0]["field"] == "lines[0].quantity"


def test_ip_address_accepts_ipv6() -> None:
    prop = _schemas()["ActivityEvent"]["properties"]["ip_address"]
    assert "ipv4" not in str(prop)
    assert prop["x-visible-to"] == ["super_admin"]


def test_stock_balance_has_derived_in_transit() -> None:
    schema = _schemas()["StockBalance"]
    assert "qty_in_transit" in schema["required"]
    assert "Quantity" in str(schema["properties"]["qty_in_transit"])


def test_quantity_input_rejects_zero() -> None:
    pattern = _schemas()["QuantityInput"]["pattern"]
    for bad in ("0", "0.0", "0.000", "00"):
        assert re.fullmatch(pattern, bad) is None
    for good in ("1", "0.001", "2.500", "10"):
        assert re.fullmatch(pattern, good) is not None
    assert re.fullmatch(_schemas()["QuantityInputOrZero"]["pattern"], "0") is not None


def test_brand_and_item_create_use_the_same_integer_id() -> None:
    schemas = _schemas()
    option = schemas["IdOption"]["properties"]["value"]
    assert option == {"$ref": "#/components/schemas/Id"}
    assert schemas["ItemCreate"]["properties"]["brand"] == option
    brands = schemas["ItemFieldDefinitions"]["properties"]["brands"]["items"]
    assert brands == {"$ref": "#/components/schemas/IdOption"}


def test_receive_note_and_lines_rules_are_in_the_schema() -> None:
    check = Draft202012Validator(
        {**_schemas()["DispatchReceive"], "components": {"schemas": _schemas()}}
    )
    line = {"line_id": 1, "quantity_received": "5", "quantity_accepted": "3"}
    assert check.is_valid({"decision": "approve_all"})
    assert not check.is_valid({"decision": "approve_all", "lines": [line]})
    assert not check.is_valid({"decision": "approve_partial", "lines": [line]})
    assert not check.is_valid({"decision": "approve_partial", "note": "x"})
    assert check.is_valid({"decision": "approve_partial", "note": "x", "lines": [line]})
    assert not check.is_valid({"decision": "reject", "note": "x"})
    assert check.is_valid({"decision": "reject", "note": "x", "lines": [line]})


def test_replay_header_and_no_200_replay_responses() -> None:
    op = _op(_spec(), "post", "/api/v1/sales/")
    assert "Idempotent-Replayed" in op["responses"]["201"]["headers"]
    assert "200" not in op["responses"]


def test_owner_decisions_oq23_are_in_the_matrix_and_the_contract() -> None:
    spec = _spec()
    assert "x-owner-pending" not in spec
    assert len(MATRIX) == 57
    for path, method, action in (
        ("/api/v1/auth/change-password/", "post", "auth.change_password"),
        ("/api/v1/stock/reorder-levels/{item_id}/", "put", "stock.set_reorder_level"),
    ):
        op = _op(spec, method, path)
        assert op["x-action-id"] == [action]
        assert action in MATRIX
        assert "x-owner-pending" not in op
    assert _op(spec, "put", "/api/v1/stock/reorder-levels/{item_id}/")["x-roles"] == [
        "super_admin",
        "warehouse_admin",
    ]
    assert _op(spec, "post", "/api/v1/auth/change-password/")["x-roles"] == [
        "super_admin",
        "warehouse_admin",
        "branch_admin",
        "front_staff",
    ]
    assert spec["info"]["version"] == "0.2.0"


def test_password_change_required_is_documented() -> None:
    spec = _spec()
    forbidden = spec["components"]["responses"]["Forbidden"]
    example = forbidden["content"]["application/json"]["examples"]["password_change_required"]
    assert example["value"]["code"] == "password_change_required"
    assert "must_change_password" in _schemas()["Me"]["required"]
    assert "password_change_required" in spec["info"]["description"]


def test_import_requires_unit_cost_and_shows_it_to_cost_roles_only() -> None:
    spec = _spec()
    row = _schemas()["ImportPreviewRow"]
    assert "unit_cost" in row["required"]
    assert row["properties"]["unit_cost"]["x-visible-to"] == ["super_admin", "warehouse_admin"]
    assert "reorder_level" in row["properties"]
    assert _schemas()["ImportReport"]["properties"]["preview"]["items"] == {
        "$ref": "#/components/schemas/ImportPreviewRow"
    }
    dry_run = _op(spec, "post", "/api/v1/imports/dry-run/")
    assert dry_run["x-field-action-id"] == ["field.cost.read"]
    assert dry_run["x-roles"] == ["super_admin", "warehouse_admin"]
    assert "unit_cost" in str(_schemas()["ImportUpload"])


def test_bin_label_is_restored_and_audit_action_is_an_open_string() -> None:
    schemas = _schemas()
    assert "bin_label" in schemas["StockBalance"]["properties"]
    assert "bin_label" not in schemas["StockBalance"]["required"]
    action = schemas["AuditAction"]
    assert action["type"] == "string"
    assert "enum" not in action
    assert "dispatch.received" in action["x-known-values"]
    prop = schemas["ActivityEvent"]["properties"]["action"]
    assert prop == {"$ref": "#/components/schemas/AuditAction"}


# --- the validator rejects bad contracts, each for the right reason -------------------


def _mutations() -> dict[str, tuple[Any, str]]:
    def drop_action_id(s: dict[str, Any]) -> None:
        del _op(s, "get", "/api/v1/items/")["x-action-id"]

    def add_float(s: dict[str, Any]) -> None:
        s["components"]["schemas"]["PriceSet"]["properties"]["amount"] = {"type": "number"}

    def leak_cost(s: dict[str, Any]) -> None:
        del s["components"]["schemas"]["Item"]["properties"]["average_cost"]["x-visible-to"]

    def cost_via_ref(s: dict[str, Any]) -> None:
        s["components"]["schemas"]["StockBalance"]["properties"]["item"] = {
            "$ref": "#/components/schemas/Item"
        }

    def cost_inline_in_path(s: dict[str, Any]) -> None:
        content = _op(s, "get", "/api/v1/prices/{item_id}/")["responses"]["200"]["content"]
        content["application/json"]["schema"] = {
            "type": "object",
            "properties": {"unit_cost": {"$ref": "#/components/schemas/Money"}},
        }

    def drop_field_action_get_item(s: dict[str, Any]) -> None:
        del _op(s, "get", "/api/v1/items/{item_id}/")["x-field-action-id"]

    def drop_field_action_grn(s: dict[str, Any]) -> None:
        for method, path in (
            ("post", "/api/v1/goods-receipts/"),
            ("get", "/api/v1/goods-receipts/"),
            ("get", "/api/v1/goods-receipts/{receipt_id}/"),
        ):
            del _op(s, method, path)["x-field-action-id"]

    def cost_required_for_all(s: dict[str, Any]) -> None:
        s["components"]["schemas"]["Item"]["required"].append("average_cost")

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
        content = _op(s, "get", "/api/v1/branches/")["responses"]["200"]["content"]
        content["application/json"]["schema"] = {
            "type": "array",
            "items": {"$ref": "#/components/schemas/Branch"},
        }

    def bad_schema(s: dict[str, Any]) -> None:
        s["components"]["schemas"]["Id"]["minimum"] = "one"

    def money_not_shared(s: dict[str, Any]) -> None:
        s["components"]["schemas"]["Sale"]["properties"]["total"] = {"type": "string"}

    def missing_endpoint(s: dict[str, Any]) -> None:
        del s["paths"]["/api/v1/sales/{sale_id}/cancel/"]

    def old_openapi(s: dict[str, Any]) -> None:
        s["openapi"] = "3.0.3"

    def no_replay_header(s: dict[str, Any]) -> None:
        del _op(s, "post", "/api/v1/sales/")["responses"]["201"]["headers"]

    def import_cost_no_field_action(s: dict[str, Any]) -> None:
        del _op(s, "post", "/api/v1/imports/dry-run/")["x-field-action-id"]

    def import_cost_unmarked(s: dict[str, Any]) -> None:
        del s["components"]["schemas"]["ImportPreviewRow"]["properties"]["unit_cost"][
            "x-visible-to"
        ]

    return {
        "no action id": (drop_action_id, "x-action-id (a list) is required"),
        "float": (add_float, "floating point"),
        "cost without x-visible-to": (leak_cost, "cost field must carry x-visible-to"),
        "cost via $ref": (cost_via_ref, "reaches cost field average_cost"),
        "cost inline in a path": (cost_inline_in_path, "cost field must carry x-visible-to"),
        "getItem without field action": (drop_field_action_get_item, "no x-field-action-id"),
        "GRN without field action": (drop_field_action_grn, "reaches cost field unit_cost"),
        "cost required for all roles": (cost_required_for_all, "must not see cost"),
        "no idempotency": (drop_idempotency, "Idempotency-Key is needed"),
        "no replay header": (no_replay_header, "Idempotent-Replayed"),
        "wrong roles": (wrong_roles, "x-roles"),
        "broken ref": (broken_ref, "unresolved $ref"),
        "invariant endpoint": (invariant_endpoint, "must have no endpoint"),
        "no 403": (drop_403, "must document 403"),
        "unpaginated list": (unpaginated_list, "paginated or marked x-unpaginated"),
        "bad schema": (bad_schema, "invalid schema"),
        "money not shared": (money_not_shared, "shared Money schema"),
        "missing endpoint": (missing_endpoint, "action sale.cancel has no endpoint"),
        "wrong version": (old_openapi, "3.1"),
        "import preview cost without field action": (
            import_cost_no_field_action,
            "reaches cost field unit_cost",
        ),
        "import preview cost unmarked": (
            import_cost_unmarked,
            "cost field must carry x-visible-to",
        ),
    }


@pytest.mark.parametrize("name", list(_mutations()))
def test_validator_rejects(name: str) -> None:
    mutate, expected = _mutations()[name]
    spec = copy.deepcopy(_spec())
    mutate(spec)
    problems = _problems(spec)
    assert any(expected in p for p in problems), f"{name}: expected {expected!r} in {problems}"

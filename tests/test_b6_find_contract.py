"""B6.3 Find (search plus other branches' quantities, branch name and quantity only) and the generated schema
against the published contract for the Day 6 operations (sales, item imports)."""

from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
import yaml
from django.core.management import call_command
from rest_framework.test import APIClient

from inventory.models import Brand, Category, Item, ItemPrice, ItemStatus
from stock_ledger.models import Bucket, MovementType, SourceType
from stock_ledger.services import StockChange, post_stock_changes
from tests.api import call, client_as
from tests.test_b3_matrix import CONTRACT, METHODS, props, query_names
from tests.test_b4_contract import first_schema
from tests.test_b6_sales import COST_WORDS, SALES, bal, keys, sell, stock

B6_PREFIXES = ("/api/v1/sales/", "/api/v1/costed-sales/", "/api/v1/item-imports/")


@pytest.fixture
def laptop(locations: Any) -> Item:
    item = Item.objects.create(
        sku="SKU-L",
        name="HP EliteBook 840",
        category=Category.objects.get(name="Laptop"),
        brand=Brand.objects.create(name="HP"),
        status=ItemStatus.ACTIVE,
        model_name="840 G8",
    )
    ItemPrice.objects.create(item=item, selling_price=Decimal("3500.00"))
    return item


# ---------- B6.3 find ----------


@pytest.mark.parametrize("role", ["sa", "wa", "ba", "fs"])
def test_every_role_can_search_and_look_up_other_branches(
    role: str, users: dict[str, Any], locations: Any, laptop: Item
) -> None:
    stock(locations["a"], laptop, 5)
    stock(locations["b"], laptop, 7)
    stock(locations["wh"], laptop, 40)
    client = client_as(users[role])
    if role == "fs":
        assert (
            call(client, "PUT", "/api/v1/working-branch/", {"branch_id": locations["a"].pk}).status_code
            == 200
        )
    for term in ("elitebook", "SKU-L", "hp", "840"):  # name, SKU, brand, model
        found = client.get("/api/v1/items/", {"q": term})
        assert found.status_code == 200 and [i["sku"] for i in found.json()["results"]] == ["SKU-L"], term
    rows = client.get(f"/api/v1/items/{laptop.pk}/branch-availability/").json()
    assert all(set(r) == {"branch_id", "branch_name", "kind", "quantity"} for r in rows)
    by_name = {r["branch_name"]: r["quantity"] for r in rows}
    assert by_name["Branch B"] == 7
    # 0.8.0: SA also sees warehouses; WA never their own; BA and FS branches only
    assert ("Central Warehouse" in by_name) == (role == "sa")
    assert by_name.get("Central Warehouse", 40) == 40
    assert not (keys(rows) & set(COST_WORDS)) and "price" not in str(rows).lower()


def test_the_lookup_shows_available_not_on_hand_and_follows_sales(
    users: dict[str, Any], locations: Any, laptop: Item
) -> None:
    stock(locations["b"], laptop, 7)
    post_stock_changes(
        [
            StockChange(
                locations["b"], laptop, Bucket.RESERVED, 2, MovementType.DISPATCH, SourceType.DISPATCH, 5, 5
            )
        ],
        actor=None,
    )
    stock(locations["a"], laptop, 3)
    sa = client_as(users["sa"])
    assert call(sa, "PUT", "/api/v1/working-branch/", {"branch_id": locations["a"].pk}).status_code == 200
    url = f"/api/v1/items/{laptop.pk}/branch-availability/"
    assert {r["branch_name"]: r["quantity"] for r in sa.get(url).json()} == {
        "Branch B": 5,
        "Central Warehouse": 0,  # SA also sees warehouses (0.8.0)
    }  # 7 on hand - 2 reserved
    ba_b = client_as(users["ba"])  # BA of branch A looks at the others
    assert {r["branch_name"]: r["quantity"] for r in ba_b.get(url).json()} == {"Branch B": 5}
    assert sell(sa, [(laptop, 3)]).status_code == 201  # own sale: branch A is never listed, B unchanged
    assert {r["branch_name"]: r["quantity"] for r in ba_b.get(url).json()} == {"Branch B": 5}
    assert bal(locations["a"], laptop) == (0, 0)


def test_the_lookup_hides_inactive_branches_and_never_leaks_sales_or_other_stock_rows(
    users: dict[str, Any], locations: Any, laptop: Item
) -> None:
    stock(locations["b"], laptop, 7)
    fs = client_as(users["fs"])
    assert call(fs, "PUT", "/api/v1/working-branch/", {"branch_id": locations["a"].pk}).status_code == 200
    # isolation still holds around the exception: the full stock list and sales stay branch-scoped
    assert fs.get("/api/v1/stock/", {"location_id": locations["b"].pk}).status_code == 403
    assert [r["location_id"] for r in fs.get("/api/v1/stock/").json()["results"]] == []
    assert fs.get(SALES, {"branch": locations["b"].pk}).status_code == 403
    locations["b"].is_active = False
    locations["b"].save()
    assert fs.get(f"/api/v1/items/{laptop.pk}/branch-availability/").json() == []
    assert APIClient().get(f"/api/v1/items/{laptop.pk}/branch-availability/").status_code == 401


# ---------- the generated schema against the contract ----------


def b6_operations(spec: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    return {
        (p, m): op
        for p, item in spec["paths"].items()
        if p.startswith(B6_PREFIXES)
        for m, op in item.items()
        if m in METHODS
    }


def test_generated_schema_matches_the_contract_for_every_b6_operation(tmp_path: Path) -> None:
    out = tmp_path / "schema.yaml"
    call_command("spectacular", file=str(out))
    generated = yaml.safe_load(out.read_text(encoding="utf-8"))
    contract = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))
    gen_ops, ref_ops = b6_operations(generated), b6_operations(contract)
    assert set(gen_ops) == set(ref_ops) and len(ref_ops) == 7  # nothing missing, nothing extra
    for key, ref in ref_ops.items():
        gen = gen_ops[key]
        assert gen["operationId"] == ref["operationId"], key
        assert set(gen["responses"]) <= set(ref["responses"]), key
        gen_header = {p["name"] for p in gen.get("parameters", []) if p["in"] == "header"}
        ref_header = {
            "Idempotency-Key"
            for p in ref.get("parameters", [])
            if p.get("$ref", "").endswith("/IdempotencyKey")
        }
        assert gen_header == ref_header, key
        assert query_names(generated, gen, {}) == query_names(contract, ref, {}), key
        for code in ("200", "201"):
            if code in ref["responses"] and "content" in ref["responses"][code]:
                ref_schema = first_schema(ref["responses"][code]["content"])
                gen_schema = first_schema(gen["responses"][code]["content"])
                assert props(generated, gen_schema) == props(contract, ref_schema), (key, code)
        if "requestBody" in ref:
            ref_body = first_schema(ref["requestBody"]["content"])
            gen_body = first_schema(gen["requestBody"]["content"])
            assert props(generated, gen_body) == props(contract, ref_body), key
    schemas = contract["components"]["schemas"]
    assert set(schemas["Sale"]["properties"]) == set(generated["components"]["schemas"]["Sale"]["properties"])
    assert not (set(schemas["Sale"]["properties"]["lines"]["items"]["properties"]) & set(COST_WORDS))

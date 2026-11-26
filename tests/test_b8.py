"""B8.1-B8.3: Sprint 2 end-to-end and isolation hardening."""

from decimal import Decimal
from typing import Any

from inventory.models import Brand, Category, Item, ItemCost, ItemPrice, StockBalance
from sales.models import Sale
from stock_ledger.models import StockMovement
from tests.api import call, client_as

GRN = "/api/v1/goods-receipts/"
TRF = "/api/v1/dispatches/"
SALES = "/api/v1/sales/"


def stock_row(location: Any, item: Item) -> tuple[int, int]:
    row = StockBalance.objects.get(location=location, item=item)
    return row.on_hand, row.reserved


def test_mvp_happy_path_receipt_dispatch_branch_receive_sale_and_find(
    users: dict[str, Any], locations: Any
) -> None:
    category = Category.objects.get(name="Laptop")
    item = Item.objects.create(
        sku="SKU-HAPPY",
        name="HP Pavilion Happy",
        model_name="Pavilion",
        category=category,
        brand=Brand.objects.create(name="HP"),
        status="active",
    )
    ItemPrice.objects.create(item=item, selling_price=Decimal("1250.00"))

    warehouse = client_as(users["wa"])
    receipt = call(
        warehouse,
        "POST",
        GRN,
        {"supplier_name": "Acme", "lines": [{"item_id": item.pk, "quantity": 10, "unit_cost": "900.00"}]},
    )
    assert receipt.status_code == 201
    assert stock_row(locations["wh"], item) == (10, 0)

    dispatch = call(
        warehouse,
        "POST",
        TRF,
        {"destination_id": locations["a"].pk, "lines": [{"item_id": item.pk, "quantity": 4}]},
    )
    assert dispatch.status_code == 201
    assert stock_row(locations["wh"], item) == (10, 4)

    branch_admin = client_as(users["ba"])
    line = dispatch.json()["lines"][0]
    receive = call(
        branch_admin,
        "POST",
        f"{TRF}{dispatch.json()['id']}/receive/",
        {
            "decision": "approve_all",
            "lines": [{"line_id": line["id"], "qty_received": 4, "qty_accepted": 4}],
        },
    )
    assert receive.status_code == 200
    assert stock_row(locations["wh"], item) == (6, 0)
    assert stock_row(locations["a"], item) == (4, 0)

    sale = call(
        branch_admin,
        "POST",
        SALES,
        {"payment_method": "cash", "lines": [{"item_id": item.pk, "quantity": 1}]},
    )
    assert sale.status_code == 201
    assert sale.json()["total"] == "1250.00"
    assert stock_row(locations["a"], item) == (3, 0)
    assert Sale.objects.count() == 1
    assert StockMovement.objects.filter(source_ref=sale.json()["reference"]).exists()
    assert ItemCost.objects.get(item=item).average_cost == Decimal("900.0000")

    found = branch_admin.get("/api/v1/items/", {"q": "Pavilion"})
    assert found.status_code == 200
    assert [row["sku"] for row in found.json()["results"]] == ["SKU-HAPPY"]
    availability = branch_admin.get(f"/api/v1/items/{item.pk}/branch-availability/")
    assert availability.status_code == 200
    assert {row["branch_name"]: row["quantity"] for row in availability.json()} == {"Branch B": 0}


def test_permission_isolation_across_workflows(users: dict[str, Any], locations: Any) -> None:
    category = Category.objects.get(name="Laptop")
    item = Item.objects.create(
        sku="SKU-ISOLATE",
        name="Isolation Laptop",
        model_name="I1",
        category=category,
        brand=Brand.objects.create(name="ISO"),
        status="active",
    )
    ItemPrice.objects.create(item=item, selling_price=Decimal("100.00"))

    warehouse = client_as(users["wa"])
    receipt = call(
        warehouse,
        "POST",
        GRN,
        {"supplier_name": "Acme", "lines": [{"item_id": item.pk, "quantity": 5, "unit_cost": "50.00"}]},
    )
    assert receipt.status_code == 201
    dispatch = call(
        warehouse,
        "POST",
        TRF,
        {"destination_id": locations["b"].pk, "lines": [{"item_id": item.pk, "quantity": 2}]},
    )
    assert dispatch.status_code == 201

    front_staff = client_as(users["fs"])
    pick = call(
        front_staff,
        "PUT",
        "/api/v1/working-branch/",
        {"branch_id": locations["a"].pk},
    )
    assert pick.status_code == 200
    assert front_staff.get("/api/v1/stock/", {"location_id": locations["b"].pk}).status_code == 403
    assert front_staff.get(SALES, {"branch": locations["b"].pk}).status_code == 403
    assert front_staff.get(f"{TRF}{dispatch.json()['id']}/").status_code == 404
    assert call(front_staff, "POST", SALES, {"payment_method": "cash", "lines": []}).status_code == 400

    branch_a_admin = client_as(users["ba"])
    assert branch_a_admin.get(f"{TRF}{dispatch.json()['id']}/").status_code == 404

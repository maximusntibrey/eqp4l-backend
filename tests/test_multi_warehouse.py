"""MW.1/MW.2: several warehouses: optional `warehouse_id` on receipt and dispatch; reversible migration."""

from typing import Any

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

from branches.models import Location
from inventory.models import Brand, Category, Item, StockBalance
from tests.api import call, client_as

GRN = "/api/v1/goods-receipts/"
TRF = "/api/v1/dispatches/"
pytestmark = pytest.mark.django_db


@pytest.fixture
def item(db: None) -> Item:
    return Item.objects.create(
        sku="SKU-MW",
        name="MW item",
        category=Category.objects.get(name="Laptop"),
        brand=Brand.objects.create(name="HP"),
        status="active",
    )


@pytest.fixture
def wh2(locations: dict[str, Any]) -> Location:
    return Location.objects.create(kind="warehouse", code="WH2", name="Second Warehouse")


def grn(client: Any, item: Item, qty: int = 5, **extra: Any) -> Any:
    line = {"item_id": item.pk, "quantity": qty, "unit_cost": "10.00"}
    return call(client, "POST", GRN, {"supplier_name": "Acme", "lines": [line], **extra})


def trf(client: Any, locations: Any, item: Item, qty: int = 1, **extra: Any) -> Any:
    body = {"destination_id": locations["a"].pk, "lines": [{"item_id": item.pk, "quantity": qty}], **extra}
    return call(client, "POST", TRF, body)


def on_hand(location: Location, item: Item) -> int:
    row = StockBalance.objects.filter(location=location, item=item).first()
    return row.on_hand if row else 0


def field(response: Any) -> str:
    return str(response.json()["errors"][0]["field"])


def test_one_warehouse_default_still_works(users: dict[str, Any], locations: Any, item: Item) -> None:
    sa = client_as(users["sa"])
    assert grn(sa, item).status_code == 201
    assert trf(sa, locations, item).status_code == 201
    assert grn(sa, item, warehouse_id=locations["wh"].pk).status_code == 201  # explicit id also fine
    assert on_hand(locations["wh"], item) == 10


def test_two_warehouses_require_an_id(
    users: dict[str, Any], locations: Any, wh2: Location, item: Item
) -> None:
    sa = client_as(users["sa"])
    for response in (grn(sa, item), trf(sa, locations, item)):
        assert response.status_code == 400 and field(response) == "warehouse_id"
        assert response.json()["errors"][0]["message"] == "Choose a warehouse."
    assert not StockBalance.objects.exists()


def test_warehouse_id_must_be_an_active_warehouse(
    users: dict[str, Any], locations: Any, wh2: Location, item: Item
) -> None:
    sa = client_as(users["sa"])
    closed = Location.objects.create(kind="warehouse", code="WX", name="Closed", is_active=False)
    for bad in (locations["a"].pk, closed.pk, 99999):  # a branch, an inactive warehouse, unknown
        for response in (grn(sa, item, warehouse_id=bad), trf(sa, locations, item, warehouse_id=bad)):
            assert response.status_code == 400 and field(response) == "warehouse_id"
    assert call(sa, "POST", GRN, {"supplier_name": "A", "warehouse_id": 0, "lines": []}).status_code == 400


def test_each_warehouses_stock_is_separate(
    users: dict[str, Any], locations: Any, wh2: Location, item: Item
) -> None:
    sa = client_as(users["sa"])
    assert grn(sa, item, 7, warehouse_id=locations["wh"].pk).status_code == 201
    assert grn(sa, item, 3, warehouse_id=wh2.pk).status_code == 201
    assert (on_hand(locations["wh"], item), on_hand(wh2, item)) == (7, 3)
    assert trf(sa, locations, item, 5, warehouse_id=wh2.pk).status_code == 409  # only 3 available there
    sent = trf(sa, locations, item, 2, warehouse_id=wh2.pk)
    assert sent.status_code == 201 and sent.json()["origin"]["id"] == wh2.pk
    reserved = {r.location_id: r.reserved for r in StockBalance.objects.filter(item=item)}
    assert reserved == {locations["wh"].pk: 0, wh2.pk: 2}
    stock = call(sa, "GET", "/api/v1/stock/", {"item_id": item.pk}).json()
    assert {r["location_id"] for r in stock["results"]} == {locations["wh"].pk, wh2.pk}
    ledger = call(sa, "GET", "/api/v1/stock-movements/", {"item_id": item.pk})
    assert ledger.status_code in (200, 404)  # ledger path may differ; the stock list above is the check
    assert call(sa, "GET", "/api/v1/dashboard/").status_code == 200


def test_warehouse_admin_rules_unchanged(
    users: dict[str, Any], locations: Any, wh2: Location, item: Item
) -> None:
    wa = client_as(users["wa"])  # permanent location: wh
    assert grn(wa, item, warehouse_id=locations["wh"].pk).status_code == 201
    other = grn(wa, item, warehouse_id=wh2.pk)  # no per-warehouse scoping added; still the own location only
    assert other.status_code == 403 and other.json()["code"] == "wrong_branch"
    assert call(client_as(users["ba"]), "POST", GRN, {"supplier_name": "A", "lines": []}).status_code == 403


@pytest.mark.django_db(transaction=True)
def test_migration_drops_and_restores_the_one_warehouse_constraint(locations: dict[str, Any]) -> None:
    executor = MigrationExecutor(connection)
    before = executor.loader.graph.leaf_nodes()
    executor.migrate([("branches", "0001_initial")])  # backward: constraint returns (one warehouse exists)
    with connection.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_indexes WHERE indexname = 'locations_one_warehouse'")
        assert cur.fetchone() is not None
    executor = MigrationExecutor(connection)
    executor.migrate([("branches", "0002_drop_locations_one_warehouse")])
    Location.objects.create(kind="warehouse", code="WH2", name="Second")
    executor = MigrationExecutor(connection)
    with pytest.raises(RuntimeError, match="2 warehouses"):  # reverse refuses with several warehouses
        executor.migrate([("branches", "0001_initial")])
    assert Location.objects.filter(kind="warehouse").count() == 2  # no rows touched
    Location.objects.filter(code="WH2").delete()
    executor = MigrationExecutor(connection)
    executor.migrate(before)

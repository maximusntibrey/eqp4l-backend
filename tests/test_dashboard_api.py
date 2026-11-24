"""B3.4: dashboard shell data (table row 40): scoped by role and branch, quantities only, never any cost."""

from typing import Any

import pytest

from inventory.models import Brand, Category, Item, ItemCost, ItemStatus, StockBalance
from tests.api import call, client_as
from transfers.models import Dispatch, DispatchStatus

pytestmark = pytest.mark.django_db
URL = "/api/v1/dashboard/"


@pytest.fixture
def stocked(users: dict[str, Any], locations: Any) -> dict[str, Any]:
    category, _ = Category.objects.get_or_create(name="Laptop")
    brand = Brand.objects.create(name="HP")
    items = [
        Item.objects.create(sku=f"SKU-{i}", name=f"Item {i}", category=category, brand=brand, status=status)
        for i, status in enumerate([ItemStatus.ACTIVE, ItemStatus.ACTIVE, ItemStatus.DRAFT], start=1)
    ]
    ItemCost.objects.create(item=items[0], average_cost="800.0000")
    for loc, item, on_hand, reserved in [("wh", 0, 10, 4), ("wh", 1, 5, 0), ("a", 0, 3, 0), ("b", 1, 2, 1)]:
        StockBalance.objects.create(
            location=locations[loc], item=items[item], on_hand=on_hand, reserved=reserved
        )
    make = lambda ref, dest, status: Dispatch.objects.create(  # noqa: E731
        reference=ref,
        origin_location=locations["wh"],
        destination_location=locations[dest],
        status=status,
        dispatched_by=users["wa"],
    )
    make("TRF-000001", "a", DispatchStatus.IN_TRANSIT)
    make("TRF-000002", "a", DispatchStatus.IN_TRANSIT)
    make("TRF-000003", "b", DispatchStatus.IN_TRANSIT)
    make("TRF-000004", "a", DispatchStatus.COMPLETED)
    return {"items": items}


def test_super_admin_sees_all_locations_and_a_context_branch_does_not_narrow_it(
    users: dict[str, Any], locations: Any, stocked: Any
) -> None:
    client = client_as(users["sa"])
    body = call(client, "GET", URL).json()
    assert body["role"] == "super_admin" and body["location"] is None
    assert (body["waiting_dispatches"], body["in_transit_dispatches"], body["active_items"]) == (3, 3, 2)
    assert body["stock_per_location"] == [
        {
            "location_id": locations["wh"].pk,
            "location_name": "Central Warehouse",
            "on_hand": 15,
            "available": 11,
        },
        {"location_id": locations["a"].pk, "location_name": "Branch A", "on_hand": 3, "available": 3},
        {"location_id": locations["b"].pk, "location_name": "Branch B", "on_hand": 2, "available": 1},
    ]
    call(client, "PUT", "/api/v1/working-branch/", {"branch_id": locations["a"].pk})  # optional context only
    assert call(client, "GET", URL).json()["location"] is None  # still all branches (owner, 2026-11-24)


def test_warehouse_admin_sees_the_warehouse_and_quantities_for_every_location(
    users: dict[str, Any], locations: Any, stocked: Any
) -> None:
    body = call(client_as(users["wa"]), "GET", URL).json()
    assert body["role"] == "warehouse_admin" and body["location"]["kind"] == "warehouse"
    assert (body["waiting_dispatches"], body["in_transit_dispatches"]) == (0, 3)
    assert [r["on_hand"] for r in body["stock_per_location"]] == [15, 3, 2]


def test_branch_admin_sees_only_own_branch_and_no_stock_per_location(
    users: dict[str, Any], locations: Any, stocked: Any
) -> None:
    body = call(client_as(users["ba"]), "GET", URL).json()
    assert body["role"] == "branch_admin" and body["location"]["id"] == locations["a"].pk
    assert (body["waiting_dispatches"], body["in_transit_dispatches"]) == (
        2,
        2,
    )  # branch B's dispatch is hidden
    assert "stock_per_location" not in body


def test_front_staff_have_no_home_dashboard(users: dict[str, Any], stocked: Any) -> None:
    response = call(client_as(users["fs"]), "GET", URL)
    assert response.status_code == 403 and response.json()["code"] == "permission_denied"


def test_dashboard_never_carries_cost_for_any_role(users: dict[str, Any], stocked: Any) -> None:
    for key in users:
        response = call(client_as(users[key]), "GET", URL)
        if response.status_code == 200:
            text = response.content.decode().lower()
            assert "cost" not in text and "800.0" not in text, key


def test_empty_system_returns_zeroes(users: dict[str, Any], locations: Any) -> None:
    body = call(client_as(users["ba"]), "GET", URL).json()
    assert (body["waiting_dispatches"], body["in_transit_dispatches"], body["active_items"]) == (0, 0, 0)
    sa = call(client_as(users["sa"]), "GET", URL).json()
    assert [(r["on_hand"], r["available"]) for r in sa["stock_per_location"]] == [(0, 0)] * 3


def test_deactivated_branch_is_left_out_of_the_stock_list(
    users: dict[str, Any], locations: Any, stocked: Any
) -> None:
    sa = client_as(users["sa"])
    call(sa, "POST", f"/api/v1/branches/{locations['b'].pk}/deactivate/")
    names = [r["location_name"] for r in call(sa, "GET", URL).json()["stock_per_location"]]
    assert names == ["Central Warehouse", "Branch A"]


# ---- owner decision 2026-11-24: Super Admin works across all branches --------------------------


def test_super_admin_dashboard_is_all_branches_by_default_and_filters_to_one(
    users: dict[str, Any], locations: Any, stocked: Any
) -> None:
    sa = client_as(users["sa"])
    allb = call(sa, "GET", URL).json()
    assert allb["location"] is None and (allb["waiting_dispatches"], allb["in_transit_dispatches"]) == (3, 3)
    assert len(allb["stock_per_location"]) == 3
    one = call(sa, "GET", URL, {"branch": locations["a"].pk}).json()
    assert one["location"]["code"] == "A" and (one["waiting_dispatches"], one["in_transit_dispatches"]) == (
        2,
        2,
    )
    assert [r["location_name"] for r in one["stock_per_location"]] == ["Branch A"]
    other = call(sa, "GET", URL, {"branch": locations["b"].pk}).json()
    assert (other["waiting_dispatches"], other["in_transit_dispatches"]) == (1, 1)
    bad = call(sa, "GET", URL, {"branch": 99999})
    assert bad.status_code == 400 and bad.json()["errors"][0]["field"] == "branch"
    assert call(sa, "GET", URL, {"branch": "x"}).status_code == 400


def test_branch_filter_is_ignored_for_roles_with_a_fixed_location(
    users: dict[str, Any], locations: Any, stocked: Any
) -> None:
    ba = call(client_as(users["ba"]), "GET", URL, {"branch": locations["b"].pk}).json()
    assert ba["location"]["id"] == locations["a"].pk and ba["waiting_dispatches"] == 2
    wa = call(client_as(users["wa"]), "GET", URL, {"branch": locations["b"].pk}).json()
    assert wa["location"]["kind"] == "warehouse" and len(wa["stock_per_location"]) == 3

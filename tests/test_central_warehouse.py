"""Contract 0.8.0: warehouses behave like branches for visibility; the read-only central warehouse role.

WA acts and reads only in their own warehouse and sees other warehouses only as name, kind and quantity.
The central user reads every warehouse together and writes nothing. BA and FS are unchanged; cost never
reaches a role without `items.view_cost`.
"""

from collections.abc import Callable
from decimal import Decimal
from typing import Any

import pytest

from branches.models import Location
from inventory.models import Brand, Category, Item, ItemPrice, StockBalance
from roles.models import Role, UserRole
from tests.api import call, client_as
from tests.test_b6_sales import stock

GRN = "/api/v1/goods-receipts/"
TRF = "/api/v1/dispatches/"
pytestmark = pytest.mark.django_db
COST_WORDS = ("cost", "average_cost", "unit_cost")


@pytest.fixture
def item(db: None) -> Item:
    row = Item.objects.create(
        sku="SKU-CW",
        name="CW item",
        category=Category.objects.get(name="Laptop"),
        brand=Brand.objects.create(name="HP"),
        status="active",
    )
    ItemPrice.objects.create(item=row, selling_price=Decimal("3500.00"))
    return row


@pytest.fixture
def wh2(locations: dict[str, Any]) -> Location:
    locations["wh2"] = Location.objects.create(kind="warehouse", code="WH2", name="Second Warehouse")
    return locations["wh2"]


@pytest.fixture
def world(users: dict[str, Any], locations: dict[str, Any], wh2: Location, item: Item) -> dict[str, Any]:
    """Two warehouses with a receipt and a dispatch each, plus stock at branch A."""
    sa = client_as(users["sa"])
    receipts, dispatches = {}, {}
    for key, qty in (("wh", 7), ("wh2", 3)):
        line = {"item_id": item.pk, "quantity": qty, "unit_cost": "10.00"}
        body = {"supplier_name": "Acme", "warehouse_id": locations[key].pk, "lines": [line]}
        receipts[key] = call(sa, "POST", GRN, body).json()
        sent = {
            "warehouse_id": locations[key].pk,
            "destination_id": locations["a"].pk,
            "lines": [{"item_id": item.pk, "quantity": 1}],
        }
        dispatches[key] = call(sa, "POST", TRF, sent).json()
    stock(locations["a"], item, 5)
    return {"receipts": receipts, "dispatches": dispatches}


@pytest.fixture
def wa2(make_user: Callable[..., Any], wh2: Location) -> Any:
    return make_user("warehouse_admin", "wh2")


def ids(response: Any) -> set[Any]:
    return {r["id"] for r in response.json()["results"]}


def has_cost(payload: Any) -> bool:
    text = str(payload).lower()
    return any(word in text for word in COST_WORDS)


# ---- Warehouse Admin: own warehouse only -------------------------------------------------------


def test_wa_cannot_write_to_another_warehouse_but_can_write_to_their_own(
    users: dict[str, Any], locations: dict[str, Any], wa2: Any, item: Item, world: dict[str, Any]
) -> None:
    wa = client_as(users["wa"])  # warehouse wh
    line = {"item_id": item.pk, "quantity": 1, "unit_cost": "10.00"}
    before = StockBalance.objects.get(location=locations["wh2"], item=item).on_hand
    bad = call(wa, "POST", GRN, {"supplier_name": "X", "warehouse_id": locations["wh2"].pk, "lines": [line]})
    assert bad.status_code == 403 and bad.json()["code"] == "wrong_branch"
    sent = {
        "warehouse_id": locations["wh2"].pk,
        "destination_id": locations["a"].pk,
        "lines": [{"item_id": item.pk, "quantity": 1}],
    }
    bad = call(wa, "POST", TRF, sent)
    assert bad.status_code == 403 and bad.json()["code"] == "wrong_branch"
    assert StockBalance.objects.get(location=locations["wh2"], item=item).on_hand == before
    own = call(wa, "POST", GRN, {"supplier_name": "X", "warehouse_id": locations["wh"].pk, "lines": [line]})
    assert own.status_code == 201
    # omitted warehouse_id with several warehouses stays a 400 for WA too
    assert call(wa, "POST", GRN, {"supplier_name": "X", "lines": [line]}).status_code == 400
    # the other warehouse's own admin writes there
    other = call(client_as(wa2), "POST", GRN, {"supplier_name": "X", "lines": [line]})
    assert other.status_code == 400  # several warehouses: id required
    other = call(
        client_as(wa2),
        "POST",
        GRN,
        {"supplier_name": "X", "warehouse_id": locations["wh2"].pk, "lines": [line]},
    )
    assert other.status_code == 201


def test_wa_reads_only_their_own_warehouses_receipts_and_dispatches(
    users: dict[str, Any], world: dict[str, Any]
) -> None:
    wa = client_as(users["wa"])
    own_r, other_r = world["receipts"]["wh"]["id"], world["receipts"]["wh2"]["id"]
    assert ids(call(wa, "GET", GRN)) == {own_r}
    assert call(wa, "GET", f"{GRN}{own_r}/").status_code == 200
    gone = call(wa, "GET", f"{GRN}{other_r}/")
    assert gone.status_code == 404 and gone.json()["code"] == "not_found"
    own_d, other_d = world["dispatches"]["wh"]["id"], world["dispatches"]["wh2"]["id"]
    assert ids(call(wa, "GET", TRF)) == {own_d}
    assert call(wa, "GET", f"{TRF}{own_d}/").status_code == 200
    assert call(wa, "GET", f"{TRF}{other_d}/").status_code == 404
    wa2_view = call(wa, "GET", "/api/v1/dashboard/").json()
    assert wa2_view["in_transit_dispatches"] == 1  # only the own warehouse's dispatch


def test_wa_stock_is_own_warehouse_and_branches_never_another_warehouse(
    users: dict[str, Any], locations: dict[str, Any], world: dict[str, Any]
) -> None:
    wa = client_as(users["wa"])
    shown = {r["location_id"] for r in call(wa, "GET", "/api/v1/stock/").json()["results"]}
    assert shown == {locations["wh"].pk, locations["a"].pk}
    only = call(wa, "GET", "/api/v1/stock/", {"location_id": locations["wh2"].pk}).json()
    assert only["results"] == []
    moves = {r["location_id"] for r in call(wa, "GET", "/api/v1/stock/movements/").json()["results"]}
    assert locations["wh2"].pk not in moves and locations["wh"].pk in moves
    costed = call(wa, "GET", "/api/v1/costed-stock/").json()["results"]
    assert {r["location_id"] for r in costed} == {locations["wh"].pk}  # cost: own warehouse only


def test_wa_sees_other_warehouses_as_name_kind_and_quantity_only(
    users: dict[str, Any], locations: dict[str, Any], item: Item, world: dict[str, Any]
) -> None:
    rows = call(client_as(users["wa"]), "GET", f"/api/v1/items/{item.pk}/branch-availability/").json()
    assert all(set(r) == {"branch_id", "branch_name", "kind", "quantity"} for r in rows)
    by_id = {r["branch_id"]: r for r in rows}
    assert locations["wh"].pk not in by_id  # their own warehouse is in /stock/, not in the lookup
    other = by_id[locations["wh2"].pk]
    assert other["kind"] == "warehouse" and other["branch_name"] == "Second Warehouse"
    assert other["quantity"] == 2  # 3 received, 1 reserved by the dispatch: available only
    assert by_id[locations["a"].pk]["kind"] == "branch" and by_id[locations["a"].pk]["quantity"] == 5
    assert not has_cost(rows) and "price" not in str(rows).lower()


# ---- Central warehouse: all warehouses, read only ----------------------------------------------


def test_central_user_has_the_role_permissions_and_menu(users: dict[str, Any]) -> None:
    body = client_as(users["cw"]).get("/api/v1/auth/me/").json()
    assert body["active_role"] == "central_warehouse" and body["user"]["roles"] == ["central_warehouse"]
    assert body["user"]["permanent_location_id"] is None and body["must_pick_branch"] is False
    assert set(body["permissions"]) == {
        "items.view",
        "stock.view",
        "stock.lookup_other_branches",
        "branches.view",
        "dispatches.view",
        "find.use",
        "goods_receipts.view",
    }
    assert [m["key"] for m in body["menu"]] == ["stock", "receive_stock", "dispatch", "find"]
    assert body["home_links"] == [] and body["all_branches"] is False
    assert body["can_assign_multiple_roles"] is False


def test_central_user_sees_every_warehouse_together_without_cost(
    users: dict[str, Any], locations: dict[str, Any], world: dict[str, Any]
) -> None:
    cw = client_as(users["cw"])
    receipts = call(cw, "GET", GRN)
    assert receipts.status_code == 200 and ids(receipts) == {r["id"] for r in world["receipts"].values()}
    assert not has_cost(receipts.json())  # unit_cost is dropped for a reader without items.view_cost
    one = call(cw, "GET", f"{GRN}{world['receipts']['wh2']['id']}/")
    assert one.status_code == 200 and not has_cost(one.json())
    sa_view = call(client_as(users["sa"]), "GET", f"{GRN}{world['receipts']['wh2']['id']}/").json()
    assert sa_view["lines"][0]["unit_cost"] == "10.00"  # SA and WA still see it
    dispatches = call(cw, "GET", TRF)
    assert ids(dispatches) == {d["id"] for d in world["dispatches"].values()}
    assert call(cw, "GET", f"{TRF}{world['dispatches']['wh2']['id']}/").status_code == 200
    stock_rows = call(cw, "GET", "/api/v1/stock/").json()["results"]
    assert {r["location_id"] for r in stock_rows} == {locations["wh"].pk, locations["wh2"].pk}
    assert not has_cost(stock_rows)
    moves = call(cw, "GET", "/api/v1/stock/movements/").json()["results"]
    assert moves and {m["location_id"] for m in moves} <= {locations["wh"].pk, locations["wh2"].pk}
    assert call(cw, "GET", "/api/v1/stock/", {"location_id": locations["a"].pk}).json()["results"] == []


def test_central_user_lookup_lists_branches_and_warehouses(
    users: dict[str, Any], locations: dict[str, Any], item: Item, world: dict[str, Any]
) -> None:
    rows = call(client_as(users["cw"]), "GET", f"/api/v1/items/{item.pk}/branch-availability/").json()
    assert {r["branch_id"] for r in rows} == {locations[k].pk for k in ("wh", "wh2", "a", "b")}
    assert not has_cost(rows)


WRITES: list[tuple[str, str, Any]] = [
    ("POST", GRN, {"supplier_name": "X", "lines": [{"item_id": 1, "quantity": 1, "unit_cost": "1.00"}]}),
    ("POST", TRF, {"destination_id": 1, "lines": [{"item_id": 1, "quantity": 1}]}),
    ("POST", "/api/v1/dispatches/1/receive/", {"decision": "reject", "reason": "no"}),
    ("POST", "/api/v1/items/", {"name": "x"}),
    ("PATCH", "/api/v1/items/1/", {"name": "x"}),
    ("POST", "/api/v1/brands/", {"name": "x"}),
    ("POST", "/api/v1/branches/", {"name": "x", "code": "X", "branch_type": "branch"}),
    ("POST", "/api/v1/users/", {"full_name": "x", "roles": ["front_staff"]}),
    ("POST", "/api/v1/sales/", {"lines": []}),
    ("POST", "/api/v1/item-imports/", {}),
    ("POST", "/api/v1/shortfalls/1/resolve/", {"resolution": "confirm_loss", "quantity": 1, "note": "n"}),
]
READS_REFUSED = [
    "/api/v1/costed-stock/",
    "/api/v1/costed-items/",
    "/api/v1/costed-sales/",
    "/api/v1/dashboard/",
    "/api/v1/users/",
    "/api/v1/activity-log/",
    "/api/v1/shortfalls/",
    "/api/v1/sales/",
    "/api/v1/dispatches/waiting/",
]


@pytest.mark.parametrize(("method", "url", "body"), WRITES)
def test_central_user_cannot_write(
    method: str, url: str, body: Any, users: dict[str, Any], world: dict[str, Any], item: Item
) -> None:
    before = (StockBalance.objects.count(), Item.objects.count())
    response = call(client_as(users["cw"]), method, url, body)
    assert response.status_code == 403 and response.json()["code"] == "permission_denied", url
    assert (StockBalance.objects.count(), Item.objects.count()) == before


@pytest.mark.parametrize("url", READS_REFUSED)
def test_central_user_cannot_read_cost_or_other_roles_screens(url: str, users: dict[str, Any]) -> None:
    assert client_as(users["cw"]).get(url).status_code == 403, url


def test_central_user_cannot_act_on_a_warehouse_through_the_stock_rules(
    users: dict[str, Any], locations: dict[str, Any], world: dict[str, Any], item: Item
) -> None:
    from roles.permissions import can_act_in

    assert not any(can_act_in(users["cw"], locations[k], {}) for k in ("wh", "wh2", "a"))
    assert not has_cost(client_as(users["cw"]).get(f"/api/v1/items/{item.pk}/").json())


# ---- Branch roles unchanged -------------------------------------------------------------------


def test_branch_roles_are_unchanged(
    users: dict[str, Any], locations: dict[str, Any], item: Item, world: dict[str, Any]
) -> None:
    ba = client_as(users["ba"])  # branch a
    assert call(ba, "GET", GRN).status_code == 403  # receipts never for BA, FS
    assert ids(call(ba, "GET", TRF)) == {d["id"] for d in world["dispatches"].values()}  # to branch a
    assert call(ba, "GET", TRF, {"destination_id": locations["b"].pk}).status_code == 403
    rows = call(ba, "GET", f"/api/v1/items/{item.pk}/branch-availability/").json()
    assert {r["branch_id"] for r in rows} == {locations["b"].pk}  # branches only, never a warehouse
    assert {r["location_id"] for r in call(ba, "GET", "/api/v1/stock/").json()["results"]} == {
        locations["a"].pk
    }
    assert call(ba, "GET", "/api/v1/costed-stock/").status_code == 403
    fs = client_as(users["fs"])
    assert call(fs, "GET", GRN).status_code == 403
    assert call(fs, "PUT", "/api/v1/working-branch/", {"branch_id": locations["a"].pk}).status_code == 200
    assert len(call(fs, "GET", TRF).json()["results"]) == 2
    fs_rows = call(fs, "GET", f"/api/v1/items/{item.pk}/branch-availability/").json()
    assert {r["kind"] for r in fs_rows} == {"branch"}


# ---- Super Admin creates and assigns the role --------------------------------------------------


def test_super_admin_creates_and_assigns_the_central_role(users: dict[str, Any], locations: Any) -> None:
    sa = client_as(users["sa"])
    made = call(sa, "POST", "/api/v1/users/", {"full_name": "Central One", "roles": ["central_warehouse"]})
    assert made.status_code == 201, made.content
    body = made.json()
    assert body["roles"] == ["central_warehouse"] and body["permanent_location_id"] is None
    assert body["login_id"].startswith("USR-") and body["one_time_password"]
    located = call(
        sa,
        "POST",
        "/api/v1/users/",
        {
            "full_name": "Central Two",
            "roles": ["central_warehouse"],
            "permanent_location_id": locations["wh"].pk,
        },
    )
    assert located.status_code == 400 and located.json()["errors"][0]["field"] == "permanent_location_id"
    unknown = call(sa, "POST", "/api/v1/users/", {"full_name": "Nobody", "roles": ["central"]})
    assert unknown.status_code == 400
    fs = call(sa, "POST", "/api/v1/users/", {"full_name": "Floor Person", "roles": ["front_staff"]}).json()
    edited = call(sa, "PATCH", f"/api/v1/users/{fs['id']}/", {"roles": ["central_warehouse"]})
    assert edited.status_code == 200 and edited.json()["roles"] == ["central_warehouse"]
    # a Warehouse Admin may not create or assign it
    refused = call(
        client_as(users["wa"]), "POST", "/api/v1/users/", {"full_name": "X", "roles": ["central_warehouse"]}
    )
    assert refused.status_code == 403


def test_role_row_exists_and_a_user_can_hold_it(users: dict[str, Any]) -> None:
    role = Role.objects.get(code="central_warehouse")
    assert role.name == "Central Warehouse" and UserRole.objects.filter(role=role).count() == 1

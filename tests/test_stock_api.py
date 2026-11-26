"""B4.4 stock query API: scope per role, cost visibility, filters, branch availability, FIX-2 cost rules."""

from decimal import Decimal
from typing import Any

import pytest

from inventory.models import Brand, Category, Condition, Item, ItemCost
from inventory.services import money
from stock_ledger.models import MovementType, SourceType
from stock_ledger.services import StockChange, post_stock_changes
from tests.api import call, client_as

STOCK = "/api/v1/stock/"
COSTED = "/api/v1/costed-stock/"


@pytest.fixture
def world(locations: dict[str, Any]) -> dict[str, Any]:
    brand = Brand.objects.create(name="HP")
    category = Category.objects.get(name="Laptop")
    laptop = Item.objects.create(
        sku="SKU-A",
        name="HP Laptop",
        category=category,
        brand=brand,
        model_name="250",
        condition=Condition.NEW,
    )
    mouse = Item.objects.create(
        sku="SKU-B",
        name="Logi Mouse",
        category=category,
        brand=brand,
        model_name="M185",
        condition=Condition.NEW,
    )
    ItemCost.objects.create(item=laptop, average_cost=Decimal("2800.1250"))
    line = iter(range(1, 100))

    def put(loc: str, item: Item, on_hand: int, reserved: int = 0) -> None:
        n = next(line)
        changes = [
            StockChange(
                locations[loc],
                item,
                "on_hand",
                on_hand,
                MovementType.OPENING_BALANCE,
                SourceType.CSV_IMPORT,
                1,
                n,
            )
        ]
        if reserved:
            changes.append(
                StockChange(
                    locations[loc],
                    item,
                    "reserved",
                    reserved,
                    MovementType.DISPATCH,
                    SourceType.DISPATCH,
                    1,
                    n,
                )
            )
        post_stock_changes(changes, actor=None)

    put("wh", laptop, 20, 4)
    put("a", laptop, 5)
    put("b", laptop, 3, 1)
    put("a", mouse, 7)
    return {"laptop": laptop, "mouse": mouse, **locations}


def rows(response: Any) -> list[tuple[int, int]]:
    assert response.status_code == 200, response.content
    return [(r["location_id"], r["item_id"]) for r in response.json()["results"]]


def test_sa_and_wa_see_every_location_without_cost(users: dict[str, Any], world: dict[str, Any]) -> None:
    for key in ("sa", "wa"):
        response = client_as(users[key]).get(STOCK)
        assert len(rows(response)) == 4
        assert all("average_cost" not in r for r in response.json()["results"])
        first = response.json()["results"][0]
        assert (first["on_hand"], first["reserved"], first["available"]) == (20, 4, 16)
        assert first["location_name"] == "Central Warehouse" and first["sku"] == "SKU-A"
        assert rows(client_as(users[key]).get(STOCK, {"location_id": world["a"].pk})) == [
            (world["a"].pk, world["laptop"].pk),
            (world["a"].pk, world["mouse"].pk),
        ]


def test_branch_admin_sees_only_the_own_branch_and_other_branch_is_refused(
    users: dict[str, Any], world: dict[str, Any]
) -> None:
    ba = client_as(users["ba"])  # permanent branch A
    assert {loc for loc, _ in rows(ba.get(STOCK))} == {world["a"].pk}
    assert rows(ba.get(STOCK, {"location_id": world["a"].pk}))
    for other in ("b", "wh"):
        denied = ba.get(STOCK, {"location_id": world[other].pk})
        assert denied.status_code == 403 and denied.json()["code"] == "wrong_branch"


def test_front_staff_scope_follows_the_chosen_branch(users: dict[str, Any], world: dict[str, Any]) -> None:
    fs = client_as(users["fs"])
    assert fs.get(STOCK).status_code == 403  # no branch chosen yet
    call(fs, "PUT", "/api/v1/working-branch/", {"branch_id": world["b"].pk})
    assert rows(fs.get(STOCK)) == [(world["b"].pk, world["laptop"].pk)]
    assert fs.get(STOCK, {"location_id": world["a"].pk}).status_code == 403
    only = fs.get(STOCK).json()["results"][0]
    assert (only["on_hand"], only["reserved"], only["available"]) == (3, 1, 2)


def test_filters_search_and_bad_input(users: dict[str, Any], world: dict[str, Any]) -> None:
    sa = client_as(users["sa"])
    assert len(rows(sa.get(STOCK, {"item_id": world["mouse"].pk}))) == 1
    assert len(rows(sa.get(STOCK, {"q": "logi"}))) == 1 and len(rows(sa.get(STOCK, {"q": "SKU-A"}))) == 3
    assert len(rows(sa.get(STOCK, {"q": "hp"}))) == 4  # brand name
    assert sa.get(STOCK, {"location_id": "abc"}).status_code == 400
    assert sa.get(STOCK, {"page_size": 2}).json()["count"] == 4
    assert rows(sa.get(STOCK, {"location_id": 99999})) == []


def test_costed_stock_is_sa_all_wa_warehouse_only_and_refused_for_ba_fs(
    users: dict[str, Any], world: dict[str, Any]
) -> None:
    sa = client_as(users["sa"]).get(COSTED)
    assert len(rows(sa)) == 4
    costs = {(r["location_id"], r["item_id"]): r["average_cost"] for r in sa.json()["results"]}
    assert costs[(world["wh"].pk, world["laptop"].pk)] == "2800.13"  # 4 dp stored, 2 dp shown
    assert costs[(world["a"].pk, world["mouse"].pk)] is None  # no receipt yet
    wa = client_as(users["wa"])
    assert rows(wa.get(COSTED)) == [(world["wh"].pk, world["laptop"].pk)]
    assert rows(wa.get(COSTED, {"location_id": world["a"].pk})) == []  # OQ-8: no cost on branch quantities
    for key in ("ba", "fs"):
        assert client_as(users[key]).get(COSTED).status_code == 403


def test_unauthenticated_stock_is_401(api: Any) -> None:
    for url in (STOCK, COSTED, "/api/v1/items/1/branch-availability/"):
        assert api.get(url).status_code == 401


def test_branch_availability_shows_only_name_and_available_of_other_active_branches(
    users: dict[str, Any], world: dict[str, Any]
) -> None:
    url = f"/api/v1/items/{world['laptop'].pk}/branch-availability/"
    ba = client_as(users["ba"]).get(url)
    assert ba.status_code == 200
    assert ba.json() == [
        {"branch_id": world["b"].pk, "branch_name": "Branch B", "quantity": 2}
    ]  # not own, not warehouse
    wa = client_as(users["wa"]).get(url).json()
    assert [(r["branch_name"], r["quantity"]) for r in wa] == [("Branch A", 5), ("Branch B", 2)]
    mouse = client_as(users["wa"]).get(f"/api/v1/items/{world['mouse'].pk}/branch-availability/").json()
    assert [(r["branch_name"], r["quantity"]) for r in mouse] == [("Branch A", 7), ("Branch B", 0)]
    assert client_as(users["fs"]).get("/api/v1/items/99999/branch-availability/").status_code == 404
    world["b"].is_active = False
    world["b"].save()
    assert [r["branch_name"] for r in client_as(users["wa"]).get(url).json()] == ["Branch A"]


# ---- FIX-2: cost precision and visibility ----


def test_sale_line_cost_snapshot_is_4_dp_in_the_db_and_2_dp_in_the_api_form(
    users: dict[str, Any], world: dict[str, Any]
) -> None:
    from django.db import connection

    from sales.models import PaymentMethod, Sale, SaleLine

    # The sales endpoints arrive in Sprint 2; this pins storage (4 dp) and the API rule (2 dp).
    sale = Sale.objects.create(
        reference="SAL-000001",
        location=world["a"],
        staff=users["ba"],
        payment_method=PaymentMethod.objects.get(code="cash"),
        total=Decimal("3500.00"),
    )
    line = SaleLine.objects.create(
        sale=sale,
        item=world["laptop"],
        quantity=1,
        unit_price=Decimal("3500.00"),
        line_total=Decimal("3500.00"),
        unit_cost_snapshot=Decimal("2800.1250"),
    )
    with connection.cursor() as cursor:
        cursor.execute("SELECT unit_cost_snapshot::text FROM sales_saleline WHERE id = %s", [line.pk])
        assert cursor.fetchone() == ("2800.1250",)
    line.refresh_from_db()
    assert line.unit_cost_snapshot == Decimal("2800.1250")
    assert (
        money(line.unit_cost_snapshot) == "2800.13"
        and money(Decimal("0.0049")) == "0.00"
        and money(None) is None
    )


def test_item_and_stock_payloads_for_branch_roles_never_carry_cost(
    users: dict[str, Any], world: dict[str, Any]
) -> None:
    for key in ("ba", "fs"):
        client = client_as(users[key])
        if key == "fs":
            call(client, "PUT", "/api/v1/working-branch/", {"branch_id": world["a"].pk})
        text = client.get(STOCK).content + client.get("/api/v1/items/").content
        assert b"average_cost" not in text and b"unit_cost" not in text


# ---- movement log (contract 0.3.0) ------------------------------------------------------------------------


MOVES = "/api/v1/stock/movements/"


def test_movement_log_scope_filters_and_no_cost(users: dict[str, Any], world: dict[str, Any]) -> None:
    for key in ("sa", "wa"):
        response = client_as(users[key]).get(MOVES)
        results = response.json()["results"]
        assert response.json()["count"] == 6
        assert [r["id"] for r in results] == sorted((r["id"] for r in results), reverse=True)  # newest first
        assert b"cost" not in response.content
        assert results[0]["sku"] == "SKU-B" and results[0]["actor_login_id"] == ""
    sa = client_as(users["sa"])
    assert sa.get(MOVES, {"location_id": world["wh"].pk}).json()["count"] == 2
    assert sa.get(MOVES, {"item_id": world["mouse"].pk}).json()["count"] == 1
    assert sa.get(MOVES, {"movement_type": "dispatch"}).json()["count"] == 2
    assert sa.get(MOVES, {"movement_type": "bogus"}).status_code == 400
    assert sa.get(MOVES, {"page_size": 4}).json()["next"]


def test_movement_log_for_branch_roles_is_the_own_branch_only(
    users: dict[str, Any], world: dict[str, Any]
) -> None:
    ba = client_as(users["ba"])  # branch A
    body = ba.get(MOVES).json()
    assert body["count"] == 2 and {r["location_id"] for r in body["results"]} == {world["a"].pk}
    assert ba.get(MOVES, {"location_id": world["b"].pk}).status_code == 403
    fs = client_as(users["fs"])
    assert fs.get(MOVES).status_code == 403  # no branch chosen
    call(fs, "PUT", "/api/v1/working-branch/", {"branch_id": world["b"].pk})
    assert fs.get(MOVES).json()["count"] == 2
    assert fs.get(MOVES, {"location_id": world["a"].pk}).status_code == 403


def test_movement_log_needs_a_login(api: Any) -> None:
    assert api.get(MOVES).status_code == 401


def test_low_stock_and_reorder_level(users: dict[str, Any], world: dict[str, Any]) -> None:
    from inventory.models import StockBalance

    StockBalance.objects.filter(location=world["wh"], item=world["laptop"]).update(
        reorder_level=16
    )  # available 16
    StockBalance.objects.filter(location=world["a"], item=world["laptop"]).update(
        reorder_level=4
    )  # available 5
    for url in (STOCK, COSTED):
        got = {(r["location_id"], r["item_id"]): r for r in client_as(users["sa"]).get(url).json()["results"]}
        assert got[(world["wh"].pk, world["laptop"].pk)]["low_stock"] is True
        assert got[(world["wh"].pk, world["laptop"].pk)]["reorder_level"] == 16
    got = {
        r["location_id"]: r
        for r in client_as(users["sa"]).get(STOCK, {"item_id": world["laptop"].pk}).json()["results"]
    }
    assert got[world["a"].pk]["low_stock"] is False and got[world["b"].pk]["reorder_level"] is None
    assert got[world["b"].pk]["low_stock"] is False

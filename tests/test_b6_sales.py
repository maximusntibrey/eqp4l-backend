"""B6.1, B6.2, B6.5, B6.6: sale, sales list and detail, cancel. Every endpoint (allowed role, other roles
refused, wrong branch refused, bad input), balances, ledger and audit of each workflow, idempotency, atomic
rollback, no oversell, and the last unit under concurrency."""

import itertools
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
from threading import Barrier
from typing import Any

import pytest
from django.db import connection
from django.utils import timezone
from rest_framework.test import APIClient

from audit.models import AuditEvent
from inventory.models import Brand, Category, Item, ItemCost, ItemPrice, ItemStatus, StockBalance
from sales.models import Sale, SaleCancellation, SaleLine, SaleStatus
from stock_ledger.models import Bucket, MovementType, SourceType, StockMovement
from stock_ledger.services import StockChange, post_stock_changes
from tests.api import call, client_as

SALES = "/api/v1/sales/"
COST_WORDS = ("cost", "average_cost", "unit_cost", "unit_cost_snapshot")
_seq = itertools.count(1)


def stock(location: Any, item: Item, quantity: int, cost: str = "100.0000") -> None:
    """Opening stock through the one stock service, with its cost row."""
    ItemCost.objects.update_or_create(item=item, defaults={"average_cost": Decimal(cost)})
    post_stock_changes(
        [
            StockChange(
                location=location,
                item=item,
                bucket=Bucket.ON_HAND,
                delta=quantity,
                movement_type=MovementType.OPENING_BALANCE,
                source_type=SourceType.CSV_IMPORT,
                source_id=900_000 + next(_seq),
                source_line_id=2,
            )
        ],
        actor=None,
    )


def bal(location: Any, item: Item) -> tuple[int, int]:
    row = StockBalance.objects.filter(location=location, item=item).first()
    return (row.on_hand, row.reserved) if row else (0, 0)


@pytest.fixture
def items(locations: dict[str, Any]) -> dict[str, Item]:
    brand = Brand.objects.create(name="HP")
    cat = Category.objects.get(name="Laptop")

    def make(sku: str, price: str | None, status: str = ItemStatus.ACTIVE) -> Item:
        item = Item.objects.create(sku=sku, name=f"Item {sku}", category=cat, brand=brand, status=status)
        if price is not None:
            ItemPrice.objects.create(item=item, selling_price=Decimal(price))
        return item

    return {
        "x": make("SKU-X", "250.50"),
        "y": make("SKU-Y", "10.00"),
        "noprice": make("SKU-N", None),
        "draft": make("SKU-D", "5.00", ItemStatus.DRAFT),
    }


@pytest.fixture
def shop(users: dict[str, Any], locations: Any, items: dict[str, Item]) -> dict[str, Any]:
    """Branch A holds 5 X and 3 Y; branch B holds 4 X. Clients: SA and FS working at A, BA of A."""
    stock(locations["a"], items["x"], 5, "100.0000")
    stock(locations["a"], items["y"], 3, "2.5000")
    stock(locations["b"], items["x"], 4)
    sa, fs = client_as(users["sa"]), client_as(users["fs"])
    for client in (sa, fs):
        assert (
            call(client, "PUT", "/api/v1/working-branch/", {"branch_id": locations["a"].pk}).status_code
            == 200
        )
    return {"sa": sa, "fs": fs, "ba": client_as(users["ba"]), "wa": client_as(users["wa"])}


def sell(client: APIClient, lines: list[tuple[Item, int]], method: str = "cash", **kw: Any) -> Any:
    body = {"payment_method": method, "lines": [{"item_id": i.pk, "quantity": q} for i, q in lines]}
    return call(client, "POST", SALES, body, **kw)


def keys(node: Any) -> set[str]:
    if isinstance(node, dict):
        return set(node) | {k for v in node.values() for k in keys(v)}
    if isinstance(node, list):
        return {k for v in node for k in keys(v)}
    return set()


# ---------- B6.1 record a sale ----------


def test_sale_deducts_stock_and_writes_sale_ledger_and_audit(
    shop: dict[str, Any], users: dict[str, Any], locations: Any, items: dict[str, Item]
) -> None:
    response = sell(shop["ba"], [(items["x"], 2), (items["y"], 1)], "mobile_money")
    assert response.status_code == 201, response.content
    body = response.json()
    assert body["reference"] == f"SAL-{body['id']:06d}" and body["status"] == "completed"
    assert body["location"]["id"] == locations["a"].pk and body["staff"] == users["ba"].login_id
    assert body["payment_method"] == "mobile_money" and body["total"] == "511.00"  # 2 x 250.50 + 10.00
    assert [(ln["sku"], ln["quantity"], ln["unit_price"], ln["line_total"]) for ln in body["lines"]] == [
        ("SKU-X", 2, "250.50", "501.00"),
        ("SKU-Y", 1, "10.00", "10.00"),
    ]
    assert body["cancellation"] is None
    assert bal(locations["a"], items["x"]) == (3, 0) and bal(locations["a"], items["y"]) == (2, 0)
    assert bal(locations["b"], items["x"]) == (4, 0)  # another branch untouched
    moves = StockMovement.objects.filter(source_type=SourceType.SALE, source_id=body["id"]).order_by("id")
    assert [(m.item.sku, m.bucket, m.quantity_delta, m.balance_after, m.movement_type) for m in moves] == [
        ("SKU-X", "on_hand", -2, 3, "sale"),
        ("SKU-Y", "on_hand", -1, 2, "sale"),
    ]
    assert all(m.source_ref == body["reference"] and m.actor_id == users["ba"].pk for m in moves)
    events = AuditEvent.objects.filter(target_ref=body["reference"])
    assert [e.action for e in events] == ["sale_recorded"]
    assert events[0].location_id == locations["a"].pk and "unit_cost" not in str(events[0].after_values)
    assert AuditEvent.objects.filter(action="stock_posted", target_ref=str(moves[0].operation_id)).exists()


def test_the_price_comes_from_the_price_list_never_from_the_client(
    shop: dict[str, Any], items: dict[str, Item]
) -> None:
    body = {
        "payment_method": "cash",
        "lines": [{"item_id": items["x"].pk, "quantity": 1, "unit_price": "0.01"}],
        "total": "0.01",
    }
    response = call(shop["fs"], "POST", SALES, body)
    assert response.status_code == 201 and response.json()["total"] == "250.50"
    ItemPrice.objects.filter(item=items["x"]).update(selling_price=Decimal("300.00"))
    assert sell(shop["fs"], [(items["x"], 1)]).json()["total"] == "300.00"
    first = SaleLine.objects.order_by("id").first()
    assert first is not None and first.unit_price == Decimal("250.50")  # the old sale keeps its price


def test_cost_snapshot_is_copied_at_four_dp_and_never_in_any_sale_payload(
    shop: dict[str, Any], users: dict[str, Any], items: dict[str, Item]
) -> None:
    ItemCost.objects.filter(item=items["x"]).update(average_cost=Decimal("2800.1250"))
    sale_id = sell(shop["fs"], [(items["x"], 1)]).json()["id"]
    ItemCost.objects.filter(item=items["x"]).update(average_cost=Decimal("1.0000"))  # later cost change
    with connection.cursor() as cursor:
        cursor.execute("SELECT unit_cost_snapshot::text FROM sales_saleline WHERE sale_id = %s", [sale_id])
        assert cursor.fetchone() == ("2800.1250",)
    for key in ("sa", "ba", "fs"):  # list, detail and create never carry cost, for any role
        client = shop[key]
        for payload in (
            client.get(f"{SALES}{sale_id}/").json(),
            client.get(SALES).json(),
        ):
            assert not (keys(payload) & set(COST_WORDS)), key


@pytest.mark.parametrize("role", ["sa", "ba", "fs"])
def test_sellers_can_sell_in_their_working_branch(
    role: str, shop: dict[str, Any], locations: Any, items: dict[str, Item]
) -> None:
    response = sell(shop[role], [(items["y"], 1)])
    assert response.status_code == 201 and response.json()["location"]["id"] == locations["a"].pk


def test_warehouse_admin_cannot_sell(shop: dict[str, Any], items: dict[str, Item]) -> None:
    response = sell(shop["wa"], [(items["y"], 1)])
    assert response.status_code == 403 and response.json()["code"] == "permission_denied"
    assert Sale.objects.count() == 0


def test_anonymous_and_pending_password_are_refused(items: dict[str, Item], make_user: Any) -> None:
    from accounts.models import UserStatus

    assert sell(APIClient(), [(items["y"], 1)]).status_code == 401
    pending = make_user("branch_admin", "a", status=UserStatus.PENDING_ACTIVATION, must_change_password=True)
    response = sell(client_as(pending), [(items["y"], 1)])
    assert response.status_code == 403 and response.json()["code"] == "password_change_required"


def test_selling_needs_a_working_branch(
    users: dict[str, Any], items: dict[str, Item], locations: Any
) -> None:
    for key in ("fs", "sa"):  # no branch chosen yet
        response = sell(client_as(users[key]), [(items["y"], 1)])
        assert response.status_code == 403 and response.json()["code"] == "wrong_branch", key
    assert Sale.objects.count() == 0


def test_a_sale_is_always_in_the_callers_branch_not_a_chosen_other_one(
    shop: dict[str, Any], users: dict[str, Any], locations: Any, items: dict[str, Item]
) -> None:
    body = {
        "payment_method": "cash",
        "lines": [{"item_id": items["x"].pk, "quantity": 1}],
        "location_id": locations["b"].pk,
    }
    response = call(shop["ba"], "POST", SALES, body)
    assert response.status_code == 201 and response.json()["location"]["id"] == locations["a"].pk
    assert bal(locations["b"], items["x"]) == (4, 0)


@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({"payment_method": "cash", "lines": []}, "lines"),
        ({"payment_method": "cash"}, "lines"),
        ({"lines": [{"item_id": 1, "quantity": 1}]}, "payment_method"),
        ({"payment_method": "cash", "lines": [{"item_id": 1, "quantity": 0}]}, "lines.0.quantity"),
        ({"payment_method": "cash", "lines": [{"item_id": 1, "quantity": 1.5}]}, "lines.0.quantity"),
        ({"payment_method": "cash", "lines": [{"item_id": 1, "quantity": -2}]}, "lines.0.quantity"),
        ({"payment_method": "cash", "lines": [{"quantity": 1}]}, "lines.0.item_id"),
        ({"payment_method": "cheque", "lines": [{"item_id": "{x}", "quantity": 1}]}, "payment_method"),
        ({"payment_method": "cash", "lines": [{"item_id": 999999, "quantity": 1}]}, "lines[0].item_id"),
        ({"payment_method": "cash", "lines": [{"item_id": "{d}", "quantity": 1}]}, "lines[0].item_id"),
        ({"payment_method": "cash", "lines": [{"item_id": "{n}", "quantity": 1}]}, "lines[0].item_id"),
        (
            {
                "payment_method": "cash",
                "lines": [{"item_id": "{x}", "quantity": 1}, {"item_id": "{x}", "quantity": 1}],
            },
            "lines[1].item_id",
        ),
    ],
)
def test_bad_input_returns_the_standard_error_and_writes_nothing(
    body: dict[str, Any], field: str, shop: dict[str, Any], items: dict[str, Item]
) -> None:
    ids = {"{x}": items["x"].pk, "{d}": items["draft"].pk, "{n}": items["noprice"].pk}
    for line in body.get("lines", []):
        if line.get("item_id") in ids:
            line["item_id"] = ids[line["item_id"]]
    response = call(shop["fs"], "POST", SALES, body)
    assert response.status_code == 400, response.content
    error = response.json()
    assert error["code"] == "validation_error" and error["errors"][0]["field"] == field
    assert Sale.objects.count() == 0 and not StockMovement.objects.filter(movement_type="sale").exists()


def test_an_item_without_a_price_cannot_be_sold_until_it_has_one(
    shop: dict[str, Any], locations: Any, items: dict[str, Item]
) -> None:
    stock(locations["a"], items["noprice"], 5)
    response = sell(shop["fs"], [(items["noprice"], 1)])
    assert response.status_code == 400 and "no selling price" in response.json()["message"]
    assert response.json()["errors"][0]["field"] == "lines[0].item_id"
    assert bal(locations["a"], items["noprice"]) == (5, 0)
    ItemPrice.objects.create(item=items["noprice"], selling_price=Decimal("0.00"))  # a zero price is a price
    assert sell(shop["fs"], [(items["noprice"], 1)]).status_code == 201


def test_missing_or_bad_idempotency_key_is_400(shop: dict[str, Any], items: dict[str, Item]) -> None:
    assert sell(shop["fs"], [(items["y"], 1)], key=False).status_code == 400
    assert sell(shop["fs"], [(items["y"], 1)], key="not-a-uuid").status_code == 400
    assert Sale.objects.count() == 0


def test_overselling_is_blocked_and_leaves_no_trace(
    shop: dict[str, Any], users: dict[str, Any], locations: Any, items: dict[str, Item]
) -> None:
    response = sell(shop["fs"], [(items["y"], 4)])  # only 3 at branch A (X is held elsewhere too)
    assert response.status_code == 409 and response.json()["code"] == "insufficient_stock"
    assert "Item SKU-Y" in response.json()["message"] and "Branch A" in response.json()["message"]
    assert Sale.objects.count() == 0 and SaleLine.objects.count() == 0
    assert bal(locations["a"], items["y"]) == (3, 0)
    assert not AuditEvent.objects.filter(action__in=["sale_recorded"]).exists()
    # Another branch's stock never counts: 6 X exist in total, branch A has 5.
    assert sell(shop["fs"], [(items["x"], 6)]).status_code == 409


def test_a_failed_second_line_rolls_the_whole_sale_back(
    shop: dict[str, Any], locations: Any, items: dict[str, Item]
) -> None:
    ledger_before = StockMovement.objects.count()
    response = sell(shop["ba"], [(items["x"], 2), (items["y"], 9)])
    assert response.status_code == 409
    assert bal(locations["a"], items["x"]) == (5, 0) and bal(locations["a"], items["y"]) == (3, 0)
    assert Sale.objects.count() == 0 and StockMovement.objects.count() == ledger_before


def test_reserved_stock_cannot_be_sold(shop: dict[str, Any], locations: Any, items: dict[str, Item]) -> None:
    post_stock_changes(
        [
            StockChange(
                locations["a"],
                items["y"],
                Bucket.RESERVED,
                2,
                MovementType.DISPATCH,
                SourceType.DISPATCH,
                1,
                1,
            )
        ],
        actor=None,
    )
    assert sell(shop["fs"], [(items["y"], 2)]).status_code == 409  # available is 1
    assert sell(shop["fs"], [(items["y"], 1)]).status_code == 201
    assert bal(locations["a"], items["y"]) == (2, 2)


def test_selling_the_exact_remaining_quantity_empties_the_shelf_but_never_below(
    shop: dict[str, Any], locations: Any, items: dict[str, Item]
) -> None:
    assert sell(shop["fs"], [(items["y"], 3)]).status_code == 201
    assert bal(locations["a"], items["y"]) == (0, 0)
    assert sell(shop["fs"], [(items["y"], 1)]).status_code == 409
    assert bal(locations["a"], items["y"]) == (0, 0)


def test_replaying_a_sale_with_the_same_key_returns_it_again_and_writes_once(
    shop: dict[str, Any], locations: Any, items: dict[str, Item]
) -> None:
    key = uuid.uuid4()
    first = sell(shop["fs"], [(items["x"], 2)], key=key)
    again = sell(shop["fs"], [(items["x"], 2)], key=key)
    assert first.status_code == again.status_code == 201 and first.json() == again.json()
    assert Sale.objects.count() == 1 and bal(locations["a"], items["x"]) == (3, 0)
    assert StockMovement.objects.filter(movement_type="sale").count() == 1
    other = sell(shop["fs"], [(items["x"], 1)], key=key)  # same key, different body
    assert other.status_code == 409 and other.json()["code"] == "idempotency_conflict"
    assert Sale.objects.count() == 1


def test_a_refused_sale_stores_no_key_so_a_retry_after_restock_works(
    shop: dict[str, Any], locations: Any, items: dict[str, Item]
) -> None:
    key = uuid.uuid4()
    assert sell(shop["fs"], [(items["y"], 4)], key=key).status_code == 409
    stock(locations["a"], items["y"], 1)
    assert sell(shop["fs"], [(items["y"], 4)], key=key).status_code == 201


@pytest.mark.django_db(transaction=True)
def test_the_last_unit_goes_to_exactly_one_of_two_simultaneous_sales(
    users: dict[str, Any], locations: Any, items: dict[str, Item]
) -> None:
    stock(locations["a"], items["x"], 1)
    clients = [client_as(users["ba"]) for _ in range(2)]
    barrier = Barrier(2)

    def send(client: APIClient) -> int:
        try:
            barrier.wait()
            return int(sell(client, [(items["x"], 1)]).status_code)
        finally:
            connection.close()

    with ThreadPoolExecutor(2) as pool:
        assert sorted(pool.map(send, clients)) == [201, 409]
    assert bal(locations["a"], items["x"]) == (0, 0) and Sale.objects.count() == 1
    assert StockMovement.objects.filter(movement_type="sale").count() == 1


@pytest.mark.django_db(transaction=True)
def test_two_simultaneous_identical_sales_post_once(
    users: dict[str, Any], locations: Any, items: dict[str, Item]
) -> None:
    stock(locations["a"], items["x"], 5)
    clients = [client_as(users["ba"]) for _ in range(2)]
    barrier, key = Barrier(2), uuid.uuid4()

    def send(client: APIClient) -> int:
        try:
            barrier.wait()
            return int(sell(client, [(items["x"], 2)], key=key).status_code)
        finally:
            connection.close()

    with ThreadPoolExecutor(2) as pool:
        assert list(pool.map(send, clients)) == [201, 201]
    assert Sale.objects.count() == 1 and bal(locations["a"], items["x"]) == (3, 0)


# ---------- B6.2 sales list and detail ----------


@pytest.fixture
def history(
    shop: dict[str, Any], users: dict[str, Any], locations: Any, items: dict[str, Item]
) -> dict[str, Any]:
    """A: two sales (FS cash for Y, BA card for X). B: one sale by a BA of B."""
    sale_fs = sell(shop["fs"], [(items["y"], 1)], "cash").json()
    sale_ba = sell(shop["ba"], [(items["x"], 1)], "card").json()
    return {"fs": sale_fs, "ba": sale_ba}


@pytest.fixture
def branch_b_sale(
    users: dict[str, Any], locations: Any, items: dict[str, Item], make_user: Any, history: Any
) -> dict[str, Any]:
    ba_b = make_user("branch_admin", "b")
    client = client_as(ba_b)
    return {"client": client, "sale": sell(client, [(items["x"], 1)]).json(), "user": ba_b}


def refs(response: Any) -> list[str]:
    return [r["reference"] for r in response.json()["results"]]


def test_list_scopes_each_role_to_its_branch(
    shop: dict[str, Any], history: dict[str, Any], branch_b_sale: dict[str, Any], locations: Any
) -> None:
    mine = [history["ba"]["reference"], history["fs"]["reference"]]  # newest first
    assert refs(shop["ba"].get(SALES)) == mine
    assert refs(shop["fs"].get(SALES)) == mine  # FS sees all of its branch's sales (OQ-10), not only its own
    everything = refs(shop["sa"].get(SALES))
    assert everything == [branch_b_sale["sale"]["reference"], *mine]
    assert refs(shop["sa"].get(SALES, {"branch": locations["b"].pk})) == [branch_b_sale["sale"]["reference"]]
    assert refs(branch_b_sale["client"].get(SALES)) == [branch_b_sale["sale"]["reference"]]


def test_list_refuses_warehouse_admin_and_another_branch(
    shop: dict[str, Any], history: dict[str, Any], locations: Any
) -> None:
    denied = shop["wa"].get(SALES)
    assert denied.status_code == 403 and denied.json()["code"] == "permission_denied"
    for key in ("ba", "fs"):
        other = shop[key].get(SALES, {"branch": locations["b"].pk})
        assert other.status_code == 403 and other.json()["code"] == "wrong_branch", key
    assert shop["ba"].get(SALES, {"branch": locations["a"].pk}).status_code == 200
    assert APIClient().get(SALES).status_code == 401


def test_list_filters(
    shop: dict[str, Any], history: dict[str, Any], users: dict[str, Any], items: dict[str, Item]
) -> None:
    sa = shop["sa"]
    assert refs(sa.get(SALES, {"payment_method": "card"})) == [history["ba"]["reference"]]
    assert refs(sa.get(SALES, {"item_id": items["y"].pk})) == [history["fs"]["reference"]]
    assert refs(sa.get(SALES, {"staff_id": users["fs"].pk})) == [history["fs"]["reference"]]
    assert refs(sa.get(SALES, {"status": "cancelled"})) == []
    assert len(refs(sa.get(SALES, {"status": "completed"}))) == 2
    today = timezone.now().date().isoformat()
    assert len(refs(sa.get(SALES, {"date_from": today, "date_to": today}))) == 2
    tomorrow = (timezone.now() + timedelta(days=2)).date().isoformat()
    assert refs(sa.get(SALES, {"date_from": tomorrow})) == []
    assert len(refs(sa.get(SALES, {"date_to": tomorrow}))) == 2


@pytest.mark.parametrize(
    "query",
    [
        {"status": "voided"},
        {"payment_method": "cheque"},
        {"date_from": "yesterday"},
        {"item_id": "x"},
        {"branch": 0},
    ],
)
def test_list_bad_filters_are_400(query: dict[str, Any], shop: dict[str, Any]) -> None:
    response = shop["sa"].get(SALES, query)
    assert response.status_code == 400 and response.json()["code"] == "validation_error"


def test_list_is_paginated(shop: dict[str, Any], history: dict[str, Any]) -> None:
    page = shop["sa"].get(SALES, {"page_size": 1}).json()
    assert page["count"] == 2 and len(page["results"]) == 1 and page["next"]


def test_date_filter_uses_the_accra_day(shop: dict[str, Any], history: dict[str, Any]) -> None:
    ids = [history["fs"]["id"], history["ba"]["id"]]
    Sale.objects.filter(pk=ids[0]).update(sold_at=timezone.now().replace(2026, 3, 1, 23, 30))
    # 23:30 UTC on 1 March is still 1 March in Accra (UTC+0); nothing shifts a day
    assert refs(shop["sa"].get(SALES, {"date_from": "2026-03-01", "date_to": "2026-03-01"})) == [
        history["fs"]["reference"]
    ]
    assert refs(shop["sa"].get(SALES, {"date_to": "2026-02-28"})) == []


def test_detail_scope(shop: dict[str, Any], history: dict[str, Any], branch_b_sale: dict[str, Any]) -> None:
    mine, theirs = history["fs"]["id"], branch_b_sale["sale"]["id"]
    for key in ("ba", "fs", "sa"):
        assert shop[key].get(f"{SALES}{mine}/").json()["reference"] == history["fs"]["reference"]
    for key in ("ba", "fs"):  # another branch's sale looks like a missing one (OQ-30)
        assert shop[key].get(f"{SALES}{theirs}/").status_code == 404
        assert shop[key].get(f"{SALES}99999/").status_code == 404
    assert shop["sa"].get(f"{SALES}{theirs}/").status_code == 200
    assert shop["wa"].get(f"{SALES}{mine}/").status_code == 403


# ---------- B6.5 cancel ----------


def cancel(
    client: APIClient, sale_id: int, reason: str | None = "Customer changed their mind", **kw: Any
) -> Any:
    body = None if reason is None else {"reason": reason}
    return call(client, "POST", f"{SALES}{sale_id}/cancel/", body, **kw)


@pytest.mark.parametrize("role", ["ba", "sa"])
def test_cancel_reverses_stock_links_the_ledger_and_keeps_the_original(
    role: str, shop: dict[str, Any], users: dict[str, Any], locations: Any, items: dict[str, Item]
) -> None:
    sale = sell(shop["fs"], [(items["x"], 2), (items["y"], 1)]).json()
    assert bal(locations["a"], items["x"]) == (3, 0)
    response = cancel(shop[role], sale["id"])
    assert response.status_code == 200, response.content
    body = response.json()
    assert body["status"] == "cancelled" and body["reference"] == sale["reference"]
    assert body["total"] == sale["total"] and body["lines"] == sale["lines"]  # the original stays visible
    assert body["cancellation"]["reason"] == "Customer changed their mind"
    assert body["cancellation"]["cancelled_by"] == users[role].login_id
    assert body["cancellation"]["cancelled_role"] == {"ba": "branch_admin", "sa": "super_admin"}[role]
    assert bal(locations["a"], items["x"]) == (5, 0) and bal(locations["a"], items["y"]) == (3, 0)
    originals = list(StockMovement.objects.filter(movement_type="sale", source_id=sale["id"]).order_by("id"))
    reversals = list(StockMovement.objects.filter(movement_type="sale_cancellation").order_by("id"))
    assert len(originals) == len(reversals) == 2
    for original, reversal in zip(originals, reversals, strict=True):
        assert reversal.reverses_movement_id == original.pk and reversal.item_id == original.item_id
        assert reversal.quantity_delta == -original.quantity_delta and reversal.bucket == Bucket.ON_HAND
        assert (
            reversal.source_type == SourceType.SALE_CANCELLATION and reversal.source_ref == sale["reference"]
        )
        assert reversal.actor_id == users[role].pk and reversal.note == "Customer changed their mind"
    assert [m.balance_after for m in reversals] == [5, 3]
    audit = AuditEvent.objects.get(action="sale_cancelled")
    assert audit.target_ref == sale["reference"] and audit.actor_id == users[role].pk
    assert audit.before_values == {"status": "completed"}
    assert (audit.after_values or {})["status"] == "cancelled"
    assert Sale.objects.get(pk=sale["id"]).status == SaleStatus.CANCELLED
    assert SaleCancellation.objects.get(sale_id=sale["id"]).reason == "Customer changed their mind"
    assert SaleLine.objects.filter(sale_id=sale["id"]).count() == 2  # never deleted or edited


def test_cancelled_sale_stock_can_be_sold_again_and_the_list_shows_the_status(
    shop: dict[str, Any], locations: Any, items: dict[str, Item]
) -> None:
    sale = sell(shop["fs"], [(items["y"], 3)]).json()
    assert sell(shop["fs"], [(items["y"], 1)]).status_code == 409
    assert cancel(shop["ba"], sale["id"]).status_code == 200
    assert sell(shop["fs"], [(items["y"], 3)]).status_code == 201
    assert refs(shop["sa"].get(SALES, {"status": "cancelled"})) == [sale["reference"]]


def test_a_second_cancel_is_blocked_and_changes_nothing(
    shop: dict[str, Any], locations: Any, items: dict[str, Item]
) -> None:
    sale = sell(shop["fs"], [(items["x"], 2)]).json()
    assert cancel(shop["ba"], sale["id"]).status_code == 200
    second = cancel(shop["sa"], sale["id"], "again")
    assert second.status_code == 409 and second.json()["code"] == "conflict"
    assert bal(locations["a"], items["x"]) == (5, 0)
    assert StockMovement.objects.filter(movement_type="sale_cancellation").count() == 1
    assert (
        SaleCancellation.objects.count() == 1
        and AuditEvent.objects.filter(action="sale_cancelled").count() == 1
    )


def test_replaying_a_cancel_with_the_same_key_returns_it_again(
    shop: dict[str, Any], locations: Any, items: dict[str, Item]
) -> None:
    sale, key = sell(shop["fs"], [(items["x"], 2)]).json(), uuid.uuid4()
    first, again = cancel(shop["ba"], sale["id"], key=key), cancel(shop["ba"], sale["id"], key=key)
    assert first.status_code == again.status_code == 200 and first.json() == again.json()
    assert bal(locations["a"], items["x"]) == (5, 0)
    other = cancel(shop["ba"], sale["id"], "different", key=key)
    assert other.status_code == 409 and other.json()["code"] == "idempotency_conflict"


@pytest.mark.django_db(transaction=True)
def test_two_simultaneous_cancels_reverse_once(
    users: dict[str, Any], locations: Any, items: dict[str, Item]
) -> None:
    stock(locations["a"], items["x"], 3)
    ba = client_as(users["ba"])
    sale = sell(ba, [(items["x"], 2)]).json()
    clients = [client_as(users["ba"]) for _ in range(2)]
    barrier = Barrier(2)

    def send(client: APIClient) -> int:
        try:
            barrier.wait()
            return int(cancel(client, sale["id"]).status_code)
        finally:
            connection.close()

    with ThreadPoolExecutor(2) as pool:
        assert sorted(pool.map(send, clients)) == [200, 409]
    assert bal(locations["a"], items["x"]) == (3, 0)
    assert StockMovement.objects.filter(movement_type="sale_cancellation").count() == 1


@pytest.mark.parametrize("reason", [None, "", "   "])
def test_cancel_needs_a_reason(reason: str | None, shop: dict[str, Any], items: dict[str, Item]) -> None:
    sale = sell(shop["fs"], [(items["x"], 1)]).json()
    response = cancel(shop["ba"], sale["id"], reason)
    assert response.status_code == 400 and response.json()["errors"][0]["field"] == "reason"
    assert Sale.objects.get(pk=sale["id"]).status == "completed"
    assert cancel(shop["ba"], sale["id"], "x" * 1001).status_code == 400


def test_front_staff_and_warehouse_admin_cannot_cancel(shop: dict[str, Any], items: dict[str, Item]) -> None:
    sale = sell(shop["fs"], [(items["x"], 1)]).json()
    for key in ("fs", "wa"):
        response = cancel(shop[key], sale["id"])
        assert response.status_code == 403 and response.json()["code"] == "permission_denied", key
    assert APIClient().post(f"{SALES}{sale['id']}/cancel/").status_code in (401, 403)
    assert Sale.objects.get(pk=sale["id"]).status == "completed"


def test_branch_admin_cannot_cancel_another_branchs_sale(
    shop: dict[str, Any], branch_b_sale: dict[str, Any], locations: Any, items: dict[str, Item]
) -> None:
    other = branch_b_sale["sale"]
    assert cancel(shop["ba"], other["id"]).status_code == 404
    assert cancel(shop["ba"], 999999).status_code == 404
    assert Sale.objects.get(pk=other["id"]).status == "completed"
    assert cancel(shop["sa"], other["id"]).status_code == 200  # SA acts in any branch
    assert bal(locations["b"], items["x"]) == (4, 0)


def test_cancelling_in_a_deactivated_branch_is_refused(
    shop: dict[str, Any], locations: Any, items: dict[str, Item]
) -> None:
    sale = sell(shop["fs"], [(items["x"], 1)]).json()
    locations["a"].is_active = False
    locations["a"].save()
    response = cancel(shop["sa"], sale["id"])
    assert response.status_code == 403 and response.json()["code"] == "wrong_branch"
    assert Sale.objects.get(pk=sale["id"]).status == "completed"

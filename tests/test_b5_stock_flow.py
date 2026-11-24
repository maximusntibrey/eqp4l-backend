"""B5.5: warehouse receipt, dispatch, branch receiving and the waiting list.

Covers every endpoint (allowed role, other roles refused, wrong branch refused, bad input), the balances,
ledger and audit rows of each workflow, idempotency, atomic rollback, no negative stock, and concurrency.
"""

import uuid
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier
from typing import Any

import pytest
from django.db import connection
from rest_framework.test import APIClient

from audit.models import AuditEvent
from inventory.models import Brand, Category, Item, ItemCost, ItemStatus, StockBalance
from roles import constants as c
from roles.models import UserPermission
from stock_ledger.models import MovementType, StockMovement
from tests.api import call, client_as
from transfers.models import Dispatch, DispatchResolution
from warehouse.models import GoodsReceipt

GRN = "/api/v1/goods-receipts/"
TRF = "/api/v1/dispatches/"
WAITING = "/api/v1/dispatches/waiting/"


@pytest.fixture
def items(locations: dict[str, Any]) -> dict[str, Item]:
    brand = Brand.objects.create(name="HP")
    cat = Category.objects.get(name="Laptop")

    def make(sku: str, status: str = ItemStatus.ACTIVE) -> Item:
        return Item.objects.create(sku=sku, name=f"Item {sku}", category=cat, brand=brand, status=status)

    return {"x": make("SKU-X"), "y": make("SKU-Y"), "draft": make("SKU-D", ItemStatus.DRAFT)}


def bal(location: Any, item: Item) -> tuple[int, int]:
    row = StockBalance.objects.filter(location=location, item=item).first()
    return (row.on_hand, row.reserved) if row else (0, 0)


def receive_stock(client: APIClient, item: Item, quantity: int, cost: str = "10.00") -> Any:
    return call(
        client,
        "POST",
        GRN,
        {"supplier_name": "Acme", "lines": [{"item_id": item.pk, "quantity": quantity, "unit_cost": cost}]},
    )


def dispatch(client: APIClient, locations: Any, lines: list[tuple[Item, int]], to: str = "a") -> Any:
    body = {
        "destination_id": locations[to].pk,
        "lines": [{"item_id": i.pk, "quantity": q} for i, q in lines],
    }
    return call(client, "POST", TRF, body)


@pytest.fixture
def fs_receiver(users: dict[str, Any], locations: Any) -> APIClient:
    """Front Staff with the Receive stock grant, working at branch A."""
    UserPermission.objects.create(user=users["fs"], permission=c.RECEIVE_STOCK)
    client = client_as(users["fs"])
    assert call(client, "PUT", "/api/v1/working-branch/", {"branch_id": locations["a"].pk}).status_code == 200
    return client


# ---------- B5.1 warehouse receipt ----------


def test_receipt_posts_stock_ledger_audit_and_average_cost(
    users: dict[str, Any], locations: Any, items: dict[str, Item]
) -> None:
    wa = client_as(users["wa"])
    first = receive_stock(wa, items["x"], 10, "100.00")
    assert first.status_code == 201, first.content
    body = first.json()
    assert body["reference"] == f"GRN-{body['id']:06d}" and body["location_id"] == locations["wh"].pk
    assert body["received_by"] == users["wa"].login_id and body["lines"][0]["unit_cost"] == "100.00"
    assert bal(locations["wh"], items["x"]) == (10, 0)
    assert ItemCost.objects.get(item=items["x"]).average_cost == Decimal("100.0000")
    move = StockMovement.objects.get(source_ref=body["reference"])
    assert (move.movement_type, move.bucket, move.quantity_delta, move.balance_after) == (
        MovementType.SUPPLIER_RECEIPT,
        "on_hand",
        10,
        10,
    )
    assert AuditEvent.objects.filter(action="goods_receipt_confirmed", target_ref=body["reference"]).exists()
    assert AuditEvent.objects.filter(action="stock_posted", operation_id=move.operation_id).exists()
    # second receipt: (10*100 + 5*130) / 15 = 110.0000 (weighted over all on hand)
    assert receive_stock(wa, items["x"], 5, "130.00").status_code == 201
    assert ItemCost.objects.get(item=items["x"]).average_cost == Decimal("110.0000")
    assert bal(locations["wh"], items["x"]) == (15, 0)


def test_average_cost_counts_stock_at_every_location_and_restarts_from_zero(
    users: dict[str, Any], locations: Any, items: dict[str, Item]
) -> None:
    sa = client_as(users["sa"])
    receive_stock(sa, items["x"], 10, "10.00")
    d = dispatch(sa, locations, [(items["x"], 10)]).json()
    line = d["lines"][0]
    call(
        client_as(users["ba"]),
        "POST",
        f"{TRF}{d['id']}/receive/",
        {
            "decision": "approve_all",
            "lines": [{"line_id": line["id"], "qty_received": 10, "qty_accepted": 10}],
        },
    )
    assert bal(locations["wh"], items["x"]) == (0, 0)
    receive_stock(sa, items["x"], 10, "20.00")  # 10 on hand at branch A + 10 new: (100 + 200) / 20
    assert ItemCost.objects.get(item=items["x"]).average_cost == Decimal("15.0000")
    ItemCost.objects.filter(item=items["y"]).delete()
    receive_stock(sa, items["y"], 3, "7.00")
    assert ItemCost.objects.get(item=items["y"]).average_cost == Decimal("7.0000")


def test_receipt_permissions_and_reads(users: dict[str, Any], locations: Any, items: dict[str, Item]) -> None:
    body = {
        "supplier_name": "Acme",
        "lines": [{"item_id": items["x"].pk, "quantity": 1, "unit_cost": "1.00"}],
    }
    for role in ("ba", "fs"):
        client = client_as(users[role])
        assert call(client, "POST", GRN, body).status_code == 403
        assert call(client, "GET", GRN).status_code == 403
        assert call(client, "GET", f"{GRN}1/").status_code == 403
    assert GoodsReceipt.objects.count() == 0 and StockMovement.objects.count() == 0
    assert call(APIClient(), "POST", GRN, body).status_code in (401, 403)
    created = receive_stock(client_as(users["sa"]), items["x"], 2).json()
    wa = client_as(users["wa"])
    assert call(wa, "GET", f"{GRN}{created['id']}/").json()["reference"] == created["reference"]
    assert call(wa, "GET", f"{GRN}999999/").status_code == 404
    listed = call(wa, "GET", GRN, {"supplier_name": "acm"}).json()
    assert listed["count"] == 1
    assert call(wa, "GET", GRN, {"supplier_name": "nobody"}).json()["count"] == 0


@pytest.mark.parametrize(
    "mutate",
    [
        lambda b, i: b.update(supplier_name="  "),
        lambda b, i: b.update(supplier_name="s" * 201),
        lambda b, i: b.update(lines=[]),
        lambda b, i: b["lines"][0].update(quantity=0),
        lambda b, i: b["lines"][0].update(quantity=-3),
        lambda b, i: b["lines"][0].update(unit_cost="-1.00"),
        lambda b, i: b["lines"][0].update(unit_cost="1.005"),
        lambda b, i: b["lines"][0].update(item_id=999999),
        lambda b, i: b["lines"][0].update(item_id=i["draft"].pk),
        lambda b, i: b.update(lines=b["lines"] * 2),
    ],
)
def test_receipt_bad_input_is_a_standard_400_and_posts_nothing(
    users: dict[str, Any], locations: Any, items: dict[str, Item], mutate: Any
) -> None:
    body: dict[str, Any] = {
        "supplier_name": "Acme",
        "lines": [{"item_id": items["x"].pk, "quantity": 1, "unit_cost": "1.00"}],
    }
    mutate(body, items)
    response = call(client_as(users["wa"]), "POST", GRN, body)
    assert response.status_code == 400
    assert response.json()["code"] == "validation_error" and response.json()["errors"]
    assert GoodsReceipt.objects.count() == 0 and StockMovement.objects.count() == 0


def test_receipt_without_a_warehouse_is_409(users: dict[str, Any], items: dict[str, Item]) -> None:
    from branches.models import Location

    Location.objects.filter(kind="warehouse").update(is_active=False)
    assert receive_stock(client_as(users["sa"]), items["x"], 1).status_code == 409


def test_receipt_is_atomic_when_a_later_step_fails(
    users: dict[str, Any], locations: Any, items: dict[str, Item], monkeypatch: pytest.MonkeyPatch
) -> None:
    import warehouse.services as svc

    def boom(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("ledger down")

    monkeypatch.setattr(svc, "post_stock_changes", boom)
    client = client_as(users["wa"])
    client.raise_request_exception = False
    assert receive_stock(client, items["x"], 5).status_code == 500
    assert GoodsReceipt.objects.count() == 0
    assert not ItemCost.objects.filter(item=items["x"]).exists()
    assert (
        not StockBalance.objects.exists()
        and not AuditEvent.objects.filter(action="goods_receipt_confirmed").exists()
    )


def test_same_idempotency_key_receives_once_and_changed_body_is_409(
    users: dict[str, Any], locations: Any, items: dict[str, Item]
) -> None:
    wa = client_as(users["wa"])
    key = uuid.uuid4()
    body = {
        "supplier_name": "Acme",
        "lines": [{"item_id": items["x"].pk, "quantity": 4, "unit_cost": "5.00"}],
    }
    first = call(wa, "POST", GRN, body, key=key)
    again = call(wa, "POST", GRN, body, key=key)
    assert (first.status_code, again.status_code) == (201, 201) and first.json() == again.json()
    assert GoodsReceipt.objects.count() == 1 and bal(locations["wh"], items["x"]) == (4, 0)
    assert StockMovement.objects.count() == 1
    body["lines"] = [{"item_id": items["x"].pk, "quantity": 5, "unit_cost": "5.00"}]
    assert call(wa, "POST", GRN, body, key=key).status_code == 409
    assert call(wa, "POST", GRN, body, key=False).status_code == 400  # key is required


@pytest.mark.django_db(transaction=True)
def test_two_simultaneous_identical_receipts_post_once(
    users: dict[str, Any], locations: Any, items: dict[str, Item]
) -> None:
    clients = [client_as(users["wa"]) for _ in range(2)]
    barrier = Barrier(2)
    key = uuid.uuid4()
    body = {
        "supplier_name": "Acme",
        "lines": [{"item_id": items["x"].pk, "quantity": 6, "unit_cost": "2.00"}],
    }

    def send(client: APIClient) -> int:
        try:
            barrier.wait()
            return int(call(client, "POST", GRN, body, key=key).status_code)
        finally:
            connection.close()

    with ThreadPoolExecutor(2) as pool:
        assert list(pool.map(send, clients)) == [201, 201]
    assert GoodsReceipt.objects.count() == 1 and bal(locations["wh"], items["x"]) == (6, 0)


# ---------- B5.2 dispatch ----------


def test_dispatch_reserves_stock_and_writes_ledger_and_audit(
    users: dict[str, Any], locations: Any, items: dict[str, Item]
) -> None:
    receive_stock(client_as(users["wa"]), items["x"], 10)
    response = dispatch(client_as(users["wa"]), locations, [(items["x"], 4)])
    assert response.status_code == 201, response.content
    body = response.json()
    assert body["status"] == "in_transit" and body["reference"] == f"TRF-{body['id']:06d}"
    assert body["origin"]["code"] == "WH" and body["destination"]["code"] == "A"
    assert body["has_open_discrepancy"] is False and body["received_at"] is None
    line = body["lines"][0]
    assert (line["qty_sent"], line["qty_received"], line["shortfall"]) == (4, None, 0)
    assert bal(locations["wh"], items["x"]) == (10, 4) and bal(locations["a"], items["x"]) == (0, 0)
    move = StockMovement.objects.get(movement_type=MovementType.DISPATCH)
    assert (move.bucket, move.quantity_delta, move.source_ref) == ("reserved", 4, body["reference"])
    assert AuditEvent.objects.filter(action="dispatch_created", target_ref=body["reference"]).exists()
    assert AuditEvent.objects.filter(action="stock_posted", operation_id=move.operation_id).exists()
    # available (on_hand - reserved) is now 6: a further 7 is refused naming item and location
    refused = dispatch(client_as(users["wa"]), locations, [(items["x"], 7)])
    assert refused.status_code == 409 and refused.json()["code"] == "insufficient_stock"
    assert "Item SKU-X" in refused.json()["message"] and "Central Warehouse" in refused.json()["message"]
    assert Dispatch.objects.count() == 1 and bal(locations["wh"], items["x"]) == (10, 4)


def test_dispatch_with_two_lines_is_all_or_nothing(
    users: dict[str, Any], locations: Any, items: dict[str, Item]
) -> None:
    wa = client_as(users["wa"])
    receive_stock(wa, items["x"], 10)
    refused = dispatch(wa, locations, [(items["x"], 5), (items["y"], 1)])  # y has no stock
    assert refused.status_code == 409
    assert Dispatch.objects.count() == 0 and bal(locations["wh"], items["x"]) == (10, 0)
    assert StockMovement.objects.filter(movement_type=MovementType.DISPATCH).count() == 0


def test_dispatch_permissions_scope_and_bad_input(
    users: dict[str, Any], locations: Any, items: dict[str, Item]
) -> None:
    receive_stock(client_as(users["sa"]), items["x"], 10)
    for role in ("ba", "fs"):
        assert dispatch(client_as(users[role]), locations, [(items["x"], 1)]).status_code == 403
    assert Dispatch.objects.count() == 0 and bal(locations["wh"], items["x"]) == (10, 0)
    wa = client_as(users["wa"])
    good = {"destination_id": locations["a"].pk, "lines": [{"item_id": items["x"].pk, "quantity": 1}]}
    bad_bodies = [
        {**good, "destination_id": locations["wh"].pk},  # not a branch
        {**good, "destination_id": 999999},
        {**good, "lines": []},
        {**good, "lines": [{"item_id": items["x"].pk, "quantity": 0}]},
        {**good, "lines": good["lines"] * 2},
        {**good, "lines": [{"item_id": items["draft"].pk, "quantity": 1}]},
        {**good, "lines": [{"item_id": 999999, "quantity": 1}]},
        {"lines": good["lines"]},
    ]
    for body in bad_bodies:
        response = call(wa, "POST", TRF, body)
        assert response.status_code == 400 and response.json()["code"] == "validation_error", body
    locations["b"].is_active = False
    locations["b"].save()
    assert dispatch(wa, locations, [(items["x"], 1)], to="b").status_code == 400  # inactive branch
    assert Dispatch.objects.count() == 0
    assert dispatch(client_as(users["sa"]), locations, [(items["x"], 1)]).status_code == 201  # SA may too


def test_dispatch_idempotency_key_reserves_once(
    users: dict[str, Any], locations: Any, items: dict[str, Item]
) -> None:
    wa = client_as(users["wa"])
    receive_stock(wa, items["x"], 10)
    key = uuid.uuid4()
    body = {"destination_id": locations["a"].pk, "lines": [{"item_id": items["x"].pk, "quantity": 3}]}
    assert call(wa, "POST", TRF, body, key=key).status_code == 201
    assert call(wa, "POST", TRF, body, key=key).status_code == 201
    assert Dispatch.objects.count() == 1 and bal(locations["wh"], items["x"]) == (10, 3)


@pytest.mark.django_db(transaction=True)
def test_last_unit_goes_to_exactly_one_of_two_simultaneous_dispatches(
    users: dict[str, Any], locations: Any, items: dict[str, Item]
) -> None:
    receive_stock(client_as(users["wa"]), items["x"], 1)
    clients = [client_as(users["wa"]) for _ in range(2)]
    barrier = Barrier(2)

    def send(client: APIClient) -> int:
        try:
            barrier.wait()
            return int(dispatch(client, locations, [(items["x"], 1)]).status_code)
        finally:
            connection.close()

    with ThreadPoolExecutor(2) as pool:
        codes = sorted(pool.map(send, clients))
    assert codes == [201, 409], codes
    assert bal(locations["wh"], items["x"]) == (1, 1) and Dispatch.objects.count() == 1


# ---------- B5.3 branch receiving ----------


def make_dispatch(
    users: dict[str, Any], locations: Any, items: dict[str, Item], qx: int = 10
) -> dict[str, Any]:
    wa = client_as(users["wa"])
    receive_stock(wa, items["x"], 20)
    receive_stock(wa, items["y"], 20)
    made = dispatch(wa, locations, [(items["x"], qx), (items["y"], 5)])
    assert made.status_code == 201, made.content
    body: dict[str, Any] = made.json()
    return body


def lines_for(d: dict[str, Any], received: list[int], accepted: list[int]) -> list[dict[str, Any]]:
    return [
        {"line_id": ln["id"], "qty_received": r, "qty_accepted": a}
        for ln, r, a in zip(d["lines"], received, accepted, strict=True)
    ]


def test_approve_all_credits_the_branch_and_closes_the_transfer(
    users: dict[str, Any], locations: Any, items: dict[str, Item]
) -> None:
    d = make_dispatch(users, locations, items)
    response = call(
        client_as(users["ba"]),
        "POST",
        f"{TRF}{d['id']}/receive/",
        {"decision": "approve_all", "lines": lines_for(d, [10, 5], [10, 5])},
    )
    assert response.status_code == 200, response.content
    body = response.json()
    assert body["status"] == "completed" and body["has_open_discrepancy"] is False
    assert body["received_by"] == users["ba"].login_id and body["received_at"]
    assert [ln["shortfall"] for ln in body["lines"]] == [0, 0]
    assert bal(locations["wh"], items["x"]) == (10, 0) and bal(locations["a"], items["x"]) == (10, 0)
    assert bal(locations["wh"], items["y"]) == (15, 0) and bal(locations["a"], items["y"]) == (5, 0)
    rows = StockMovement.objects.filter(movement_type=MovementType.DISPATCH_RECEIPT, item=items["x"])
    assert sorted((r.location.code, r.bucket, r.quantity_delta) for r in rows) == [
        ("A", "on_hand", 10),
        ("WH", "on_hand", -10),
        ("WH", "reserved", -10),
    ]
    assert AuditEvent.objects.filter(action="dispatch_received", target_ref=d["reference"]).exists()
    assert AuditEvent.objects.filter(action="stock_posted", operation_id=rows[0].operation_id).exists()
    again = call(
        client_as(users["ba"]), "POST", f"{TRF}{d['id']}/receive/", {"decision": "reject", "reason": "x"}
    )
    assert again.status_code == 409  # one decision per dispatch
    assert bal(locations["a"], items["x"]) == (10, 0)


def test_partial_receiving_credits_accepted_and_keeps_the_shortfall_reserved(
    users: dict[str, Any], locations: Any, items: dict[str, Item]
) -> None:
    d = make_dispatch(users, locations, items)
    response = call(
        client_as(users["ba"]),
        "POST",
        f"{TRF}{d['id']}/receive/",
        {"decision": "approve_partial", "note": "5 boxes crushed", "lines": lines_for(d, [8, 5], [6, 5])},
    )
    assert response.status_code == 200, response.content
    body = response.json()
    assert body["status"] == "partially_received" and body["has_open_discrepancy"] is True
    assert body["receive_note"] == "5 boxes crushed"
    x, y = body["lines"]
    assert (x["qty_received"], x["qty_accepted"], x["qty_rejected"], x["shortfall"]) == (8, 6, 2, 4)
    assert (y["shortfall"], y["qty_rejected"]) == (0, 0)
    # sender: on_hand 20-6, reserved 10-6 (4 stay reserved); destination +6
    assert bal(locations["wh"], items["x"]) == (14, 4) and bal(locations["a"], items["x"]) == (6, 0)
    assert bal(locations["wh"], items["y"]) == (15, 0)
    reserved = StockBalance.objects.get(location=locations["wh"], item=items["x"])
    assert reserved.on_hand - reserved.reserved == 10  # available at the sender excludes the flagged 4


def test_resolution_covering_the_shortfall_clears_the_flag(
    users: dict[str, Any], locations: Any, items: dict[str, Item]
) -> None:
    d = make_dispatch(users, locations, items)
    call(
        client_as(users["ba"]),
        "POST",
        f"{TRF}{d['id']}/receive/",
        {"decision": "approve_partial", "note": "short", "lines": lines_for(d, [9, 5], [9, 5])},
    )
    line = Dispatch.objects.get(pk=d["id"]).lines.get(item=items["x"])
    DispatchResolution.objects.create(
        reference="RES-000001",
        dispatch_line=line,
        action="return_to_sender",
        quantity=1,
        note="back",
        resolved_by=users["sa"],
        resolved_role="super_admin",
    )
    assert call(client_as(users["sa"]), "GET", f"{TRF}{d['id']}/").json()["has_open_discrepancy"] is False


def test_reject_credits_nothing_and_keeps_everything_reserved(
    users: dict[str, Any], locations: Any, items: dict[str, Item]
) -> None:
    d = make_dispatch(users, locations, items)
    ba = client_as(users["ba"])
    no_reason = call(ba, "POST", f"{TRF}{d['id']}/receive/", {"decision": "reject"})
    assert no_reason.status_code == 400 and no_reason.json()["errors"][0]["field"] == "reason"
    response = call(ba, "POST", f"{TRF}{d['id']}/receive/", {"decision": "reject", "reason": "wrong goods"})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "rejected" and body["has_open_discrepancy"] is True
    assert body["receive_note"] == "wrong goods" and [ln["shortfall"] for ln in body["lines"]] == [10, 5]
    assert bal(locations["wh"], items["x"]) == (20, 10) and bal(locations["a"], items["x"]) == (0, 0)
    assert not StockMovement.objects.filter(movement_type=MovementType.DISPATCH_RECEIPT).exists()
    assert AuditEvent.objects.filter(action="dispatch_rejected", target_ref=d["reference"]).exists()


def test_receiving_bad_input_is_a_400_and_changes_nothing(
    users: dict[str, Any], locations: Any, items: dict[str, Item]
) -> None:
    d = make_dispatch(users, locations, items)
    ba = client_as(users["ba"])
    ids = [ln["id"] for ln in d["lines"]]
    full = lines_for(d, [10, 5], [10, 5])
    bad = [
        {"decision": "maybe"},
        {"decision": "approve_all"},  # lines missing
        {"decision": "approve_all", "lines": full[:1]},  # a line missing
        {"decision": "approve_all", "lines": full + full[:1]},  # a line twice
        {"decision": "approve_all", "lines": [{**full[0], "line_id": 999999}, full[1]]},
        {"decision": "approve_all", "lines": lines_for(d, [11, 5], [11, 5])},  # more than sent
        {"decision": "approve_all", "lines": lines_for(d, [9, 5], [9, 5])},  # not in full
        {"decision": "approve_all", "lines": lines_for(d, [10, 5], [9, 5])},
        {"decision": "approve_partial", "lines": full},  # note missing
        {"decision": "approve_partial", "note": "  ", "lines": full},
        {
            "decision": "approve_partial",
            "note": "n",
            "lines": lines_for(d, [5, 5], [6, 5]),
        },  # accepted > received
        {"decision": "approve_partial", "note": "n", "lines": [{**full[0], "qty_received": -1}, full[1]]},
    ]
    for body in bad:
        response = call(ba, "POST", f"{TRF}{d['id']}/receive/", body)
        assert response.status_code == 400 and response.json()["code"] == "validation_error", body
    assert call(ba, "POST", f"{TRF}999999/receive/", {"decision": "reject", "reason": "r"}).status_code == 404
    assert ids and Dispatch.objects.get(pk=d["id"]).status == "in_transit"
    assert bal(locations["a"], items["x"]) == (0, 0) and bal(locations["wh"], items["x"]) == (20, 10)


def test_only_the_destination_can_receive_and_fs_needs_the_grant(
    users: dict[str, Any], locations: Any, items: dict[str, Item], make_user: Any, fs_receiver: APIClient
) -> None:
    d = make_dispatch(users, locations, items)
    url = f"{TRF}{d['id']}/receive/"
    body = {"decision": "reject", "reason": "no"}
    other_ba = make_user("branch_admin", "b")
    wrong = call(client_as(other_ba), "POST", url, body)
    assert wrong.status_code == 403 and wrong.json()["code"] == "wrong_branch"
    assert call(client_as(users["wa"]), "POST", url, body).status_code == 403  # the sender cannot approve
    plain_fs = make_user("front_staff")
    plain_client = client_as(plain_fs)
    call(plain_client, "PUT", "/api/v1/working-branch/", {"branch_id": locations["a"].pk})
    assert call(plain_client, "POST", url, body).status_code == 403  # no grant
    assert Dispatch.objects.get(pk=d["id"]).status == "in_transit"
    # FS with the grant at the destination may; the grant works only at the working branch
    granted_at_b = client_as(users["fs"])
    call(granted_at_b, "PUT", "/api/v1/working-branch/", {"branch_id": locations["b"].pk})
    assert call(granted_at_b, "POST", url, body).status_code == 403
    assert (
        call(fs_receiver, "PUT", "/api/v1/working-branch/", {"branch_id": locations["a"].pk}).status_code
        == 200
    )
    assert call(fs_receiver, "POST", url, body).status_code == 200


def test_super_admin_may_receive_at_any_branch(
    users: dict[str, Any], locations: Any, items: dict[str, Item]
) -> None:
    d = make_dispatch(users, locations, items)
    sa = client_as(users["sa"])
    response = call(
        sa,
        "POST",
        f"{TRF}{d['id']}/receive/",
        {"decision": "approve_all", "lines": lines_for(d, [10, 5], [10, 5])},
    )
    assert response.status_code == 200 and response.json()["received_by"] == users["sa"].login_id


def test_receiving_idempotency_key_credits_once(
    users: dict[str, Any], locations: Any, items: dict[str, Item]
) -> None:
    d = make_dispatch(users, locations, items)
    ba = client_as(users["ba"])
    body = {"decision": "approve_all", "lines": lines_for(d, [10, 5], [10, 5])}
    key = uuid.uuid4()
    first = call(ba, "POST", f"{TRF}{d['id']}/receive/", body, key=key)
    again = call(ba, "POST", f"{TRF}{d['id']}/receive/", body, key=key)
    assert (first.status_code, again.status_code) == (200, 200) and first.json() == again.json()
    assert bal(locations["a"], items["x"]) == (10, 0)
    assert StockMovement.objects.filter(movement_type=MovementType.DISPATCH_RECEIPT).count() == 6


@pytest.mark.django_db(transaction=True)
def test_two_simultaneous_receiving_decisions_exactly_one_wins(
    users: dict[str, Any], locations: Any, items: dict[str, Item]
) -> None:
    d = make_dispatch(users, locations, items)
    clients = [client_as(users["ba"]) for _ in range(2)]
    barrier = Barrier(2)
    body = {"decision": "approve_all", "lines": lines_for(d, [10, 5], [10, 5])}

    def send(client: APIClient) -> int:
        try:
            barrier.wait()
            return int(call(client, "POST", f"{TRF}{d['id']}/receive/", body).status_code)
        finally:
            connection.close()

    with ThreadPoolExecutor(2) as pool:
        codes = sorted(pool.map(send, clients))
    assert codes == [200, 409], codes
    assert bal(locations["a"], items["x"]) == (10, 0) and bal(locations["wh"], items["x"]) == (10, 0)


def test_receive_failure_rolls_the_whole_decision_back(
    users: dict[str, Any], locations: Any, items: dict[str, Item], monkeypatch: pytest.MonkeyPatch
) -> None:
    import transfers.services as svc

    d = make_dispatch(users, locations, items)

    def boom(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("ledger down")

    monkeypatch.setattr(svc, "post_stock_changes", boom)
    ba = client_as(users["ba"])
    ba.raise_request_exception = False
    body = {"decision": "approve_all", "lines": lines_for(d, [10, 5], [10, 5])}
    assert call(ba, "POST", f"{TRF}{d['id']}/receive/", body).status_code == 500
    dispatch_row = Dispatch.objects.get(pk=d["id"])
    assert (
        dispatch_row.status == "in_transit"
        and dispatch_row.lines.filter(qty_accepted__isnull=False).count() == 0
    )


# ---------- B5.4 reads and waiting ----------


def test_waiting_list_per_role_and_branch(
    users: dict[str, Any], locations: Any, items: dict[str, Item], make_user: Any, fs_receiver: APIClient
) -> None:
    wa = client_as(users["wa"])
    receive_stock(wa, items["x"], 30)
    to_a = dispatch(wa, locations, [(items["x"], 1)], "a").json()
    to_b = dispatch(wa, locations, [(items["x"], 2)], "b").json()
    ba = client_as(users["ba"])
    assert [r["id"] for r in call(ba, "GET", WAITING).json()["results"]] == [to_a["id"]]
    assert [r["id"] for r in call(fs_receiver, "GET", WAITING).json()["results"]] == [to_a["id"]]
    own = call(ba, "GET", WAITING, {"branch_id": locations["a"].pk})
    assert own.status_code == 200 and own.json()["count"] == 1
    other = call(ba, "GET", WAITING, {"branch_id": locations["b"].pk})
    assert other.status_code == 403 and other.json()["code"] == "wrong_branch"
    assert call(wa, "GET", WAITING).status_code == 403  # the warehouse never sees the waiting list
    sa = client_as(users["sa"])
    assert call(sa, "GET", WAITING).status_code == 400
    assert call(sa, "GET", WAITING, {"branch_id": locations["wh"].pk}).status_code == 400
    assert call(sa, "GET", WAITING, {"branch_id": 999999}).status_code == 400
    assert [
        r["id"] for r in call(sa, "GET", WAITING, {"branch_id": locations["b"].pk}).json()["results"]
    ] == [to_b["id"]]
    # once received it is no longer waiting
    lines = lines_for(to_a, [1], [1])
    call(ba, "POST", f"{TRF}{to_a['id']}/receive/", {"decision": "approve_all", "lines": lines})
    assert call(ba, "GET", WAITING).json()["count"] == 0
    unassigned = client_as(make_user("front_staff"))  # no working branch chosen yet
    assert call(unassigned, "GET", WAITING).status_code == 403


def test_dispatch_list_and_detail_are_scoped_to_the_branch(
    users: dict[str, Any], locations: Any, items: dict[str, Item], fs_receiver: APIClient
) -> None:
    wa = client_as(users["wa"])
    receive_stock(wa, items["x"], 30)
    to_a = dispatch(wa, locations, [(items["x"], 1)], "a").json()
    to_b = dispatch(wa, locations, [(items["x"], 2)], "b").json()
    for client in (wa, client_as(users["sa"])):
        assert call(client, "GET", TRF).json()["count"] == 2
        assert call(client, "GET", TRF, {"destination_id": locations["b"].pk}).json()["count"] == 1
        assert call(client, "GET", f"{TRF}{to_b['id']}/").status_code == 200
    for client in (client_as(users["ba"]), fs_receiver):
        assert [r["id"] for r in call(client, "GET", TRF).json()["results"]] == [to_a["id"]]
        assert call(client, "GET", f"{TRF}{to_a['id']}/").json()["reference"] == to_a["reference"]
        denied = call(client, "GET", f"{TRF}{to_b['id']}/")
        assert denied.status_code == 403 and denied.json()["code"] == "wrong_branch"
        assert call(client, "GET", TRF, {"destination_id": locations["b"].pk}).status_code == 403
        assert call(client, "GET", f"{TRF}999999/").status_code == 404
    assert call(wa, "GET", TRF, {"status": "completed"}).json()["count"] == 0
    assert call(wa, "GET", TRF, {"status": "bogus"}).status_code == 400
    assert call(client_as(users["ba"]), "GET", TRF, {"status": "in_transit"}).json()["count"] == 1


def test_nothing_is_reachable_without_login(items: dict[str, Item]) -> None:
    anon = APIClient()
    for url in (GRN, f"{GRN}1/", TRF, f"{TRF}1/", WAITING):
        assert call(anon, "GET", url).status_code in (401, 403)
    assert call(anon, "POST", f"{TRF}1/receive/", {"decision": "reject", "reason": "x"}).status_code in (
        401,
        403,
    )


def test_stock_never_goes_negative_through_the_api(
    users: dict[str, Any], locations: Any, items: dict[str, Item]
) -> None:
    wa = client_as(users["wa"])
    receive_stock(wa, items["x"], 3)
    assert dispatch(wa, locations, [(items["x"], 4)]).status_code == 409
    assert dispatch(wa, locations, [(items["x"], 3)]).status_code == 201
    assert dispatch(wa, locations, [(items["x"], 1)]).status_code == 409
    for row in StockBalance.objects.all():
        assert row.on_hand >= 0 and row.reserved >= 0 and row.reserved <= row.on_hand
    for move in StockMovement.objects.all():
        assert move.balance_after >= 0


def test_receipt_after_selling_everything_restarts_the_average_at_the_new_cost(
    users: dict[str, Any], locations: Any, items: dict[str, Item]
) -> None:
    from stock_ledger.models import SourceType
    from stock_ledger.services import StockChange, post_stock_changes

    wa = client_as(users["wa"])
    receive_stock(wa, items["x"], 4, "50.00")
    post_stock_changes(
        [StockChange(locations["wh"], items["x"], "on_hand", -4, MovementType.SALE, SourceType.SALE, 1, 1)],
        actor=None,
    )
    assert bal(locations["wh"], items["x"]) == (0, 0)
    assert ItemCost.objects.get(item=items["x"]).average_cost == Decimal("50.0000")
    receive_stock(wa, items["x"], 2, "80.00")
    assert ItemCost.objects.get(item=items["x"]).average_cost == Decimal("80.0000")


def test_same_key_from_two_users_receives_twice_with_distinct_operation_ids(
    users: dict[str, Any], locations: Any, items: dict[str, Item]
) -> None:
    key = uuid.uuid4()
    body = {
        "supplier_name": "Acme",
        "lines": [{"item_id": items["x"].pk, "quantity": 1, "unit_cost": "1.00"}],
    }
    assert call(client_as(users["wa"]), "POST", GRN, body, key=key).status_code == 201
    assert call(client_as(users["sa"]), "POST", GRN, body, key=key).status_code == 201
    ops = list(GoodsReceipt.objects.values_list("operation_id", flat=True))
    assert len(ops) == 2 and len(set(ops)) == 2
    assert bal(locations["wh"], items["x"]) == (2, 0)

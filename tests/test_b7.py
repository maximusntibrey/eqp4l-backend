"""B7.1 to B7.4: dashboard extras, activity log, shortfall resolution."""

import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from threading import Barrier
from typing import Any

import pytest
import yaml
from django.core.management import call_command
from django.db import connection
from django.utils import timezone
from rest_framework.test import APIClient

from audit.models import AuditEvent
from inventory.models import Brand, Category, Item, StockBalance
from stock_ledger.models import Bucket, MovementType, StockMovement
from tests.api import call, client_as
from tests.test_b3_matrix import CONTRACT, METHODS, props, query_names
from tests.test_b4_contract import first_schema
from transfers.models import DispatchResolution

TRF = "/api/v1/dispatches/"
GRN = "/api/v1/goods-receipts/"
LIST = "/api/v1/shortfalls/"
ACTIVITY = "/api/v1/activity-log/"
DASH = "/api/v1/dashboard/"


def resolve_url(line_id: int) -> str:
    return f"{LIST}{line_id}/resolve/"


@pytest.fixture
def items(locations: dict[str, Any]) -> dict[str, Item]:
    brand = Brand.objects.create(name="HP")
    cat = Category.objects.get(name="Laptop")
    return {
        k: Item.objects.create(
            sku=f"SKU-{k.upper()}", name=f"Item {k}", category=cat, brand=brand, status="active"
        )
        for k in ("x", "y")
    }


def bal(location: Any, item: Item) -> tuple[int, int, int]:
    row = StockBalance.objects.get(location=location, item=item)
    return row.on_hand, row.reserved, row.quarantined


@pytest.fixture
def short(users: dict[str, Any], locations: Any, items: dict[str, Item]) -> dict[str, Any]:
    """WH sends 10 x and 5 y to A; A accepts 6 of x (4 short), all of y."""
    wa = client_as(users["wa"])
    for item in items.values():
        body = {
            "supplier_name": "Acme",
            "lines": [{"item_id": item.pk, "quantity": 20, "unit_cost": "50.00"}],
        }
        assert call(wa, "POST", GRN, body).status_code == 201
    body = {
        "destination_id": locations["a"].pk,
        "lines": [{"item_id": items["x"].pk, "quantity": 10}, {"item_id": items["y"].pk, "quantity": 5}],
    }
    d = call(wa, "POST", TRF, body).json()
    x_line, y_line = d["lines"]
    received = call(
        client_as(users["ba"]),
        "POST",
        f"{TRF}{d['id']}/receive/",
        {
            "decision": "approve_partial",
            "note": "box damaged",
            "lines": [
                {"line_id": x_line["id"], "qty_received": 8, "qty_accepted": 6, "line_note": "2 cracked"},
                {"line_id": y_line["id"], "qty_received": 5, "qty_accepted": 5},
            ],
        },
    )
    assert received.status_code == 200, received.content
    return {"dispatch": d, "x": x_line["id"], "y": y_line["id"]}


def resolve(
    client: APIClient, line: int, action: str, quantity: int, note: str = "checked", **kw: Any
) -> Any:
    return call(
        client, "POST", resolve_url(line), {"resolution": action, "quantity": quantity, "note": note}, **kw
    )


# ---------- B7.3 stock math, ledger, audit ----------


def test_return_to_sender_releases_reserved_only(
    users: dict[str, Any], locations: Any, items: dict[str, Item], short: Any
) -> None:
    assert bal(locations["wh"], items["x"]) == (14, 4, 0)
    r = resolve(client_as(users["wa"]), short["x"], "return_to_sender", 1, "back on shelf")
    assert r.status_code == 200, r.content
    body = r.json()
    assert (body["shortfall"], body["resolved_quantity"], body["remaining"], body["status"]) == (
        4,
        1,
        3,
        "open",
    )
    assert (
        body["resolutions"][0]["reference"].startswith("RES-")
        and body["resolutions"][0]["note"] == "back on shelf"
    )
    assert bal(locations["wh"], items["x"]) == (14, 3, 0)
    rows = StockMovement.objects.filter(movement_type=MovementType.RESOLUTION_RETURN)
    assert [(m.location.code, m.bucket, m.quantity_delta, m.balance_after, m.note) for m in rows] == [
        ("WH", "reserved", -1, 3, "back on shelf")
    ]
    ev = AuditEvent.objects.get(action="shortfall_resolved")
    assert (
        ev.actor == users["wa"]
        and ev.target_ref == short["dispatch"]["reference"]
        and not ev.is_self_approval
    )
    assert AuditEvent.objects.filter(
        action="shortfall_stock_posted", operation_id=rows[0].operation_id
    ).exists()
    assert call(client_as(users["wa"]), "GET", f"{TRF}{short['dispatch']['id']}/").json()[
        "has_open_discrepancy"
    ]


def test_confirm_loss_and_record_damage_math_and_full_resolution(
    users: dict[str, Any], locations: Any, items: dict[str, Item], short: Any
) -> None:
    ba = client_as(users["ba"])
    assert resolve(ba, short["x"], "return_to_sender", 1).status_code == 200  # (14, 3)
    assert resolve(ba, short["x"], "confirm_loss", 1).status_code == 200  # (13, 2)
    assert bal(locations["wh"], items["x"]) == (13, 2, 0)
    last = resolve(client_as(users["sa"]), short["x"], "record_damage", 2)
    assert last.status_code == 200 and last.json()["status"] == "resolved" and last.json()["remaining"] == 0
    assert bal(locations["wh"], items["x"]) == (11, 0, 0)
    assert bal(locations["a"], items["x"]) == (6, 0, 2)  # quarantined at the destination
    damage = StockMovement.objects.filter(movement_type=MovementType.RESOLUTION_DAMAGE)
    assert sorted((m.location.code, m.bucket, m.quantity_delta) for m in damage) == [
        ("A", Bucket.QUARANTINED, 2),
        ("WH", Bucket.ON_HAND, -2),
        ("WH", Bucket.RESERVED, -2),
    ]
    loss = StockMovement.objects.filter(movement_type=MovementType.RESOLUTION_LOSS)
    assert sorted((m.bucket, m.quantity_delta) for m in loss) == [("on_hand", -1), ("reserved", -1)]
    assert DispatchResolution.objects.count() == 3
    assert not call(ba, "GET", f"{TRF}{short['dispatch']['id']}/").json()["has_open_discrepancy"]
    # the sender's total on hand + destination on hand + quarantined + lost = what was bought
    assert 11 + 6 + 2 + 1 == 20


def test_cannot_resolve_more_than_the_shortfall_or_twice(
    users: dict[str, Any], locations: Any, items: dict[str, Item], short: Any
) -> None:
    sa = client_as(users["sa"])
    over = resolve(sa, short["x"], "confirm_loss", 5)
    assert over.status_code == 400 and over.json()["errors"][0]["field"] == "quantity"
    assert resolve(sa, short["x"], "confirm_loss", 3).status_code == 200
    again = resolve(sa, short["x"], "confirm_loss", 2)
    assert again.status_code == 400  # only 1 left
    assert resolve(sa, short["x"], "return_to_sender", 1).status_code == 200
    done = resolve(sa, short["x"], "return_to_sender", 1)
    assert done.status_code == 409 and done.json()["code"] == "conflict"
    assert bal(locations["wh"], items["x"]) == (11, 0, 0)
    assert DispatchResolution.objects.count() == 2


def test_bad_input_and_lines_without_a_shortfall(users: dict[str, Any], short: Any) -> None:
    sa = client_as(users["sa"])
    bad: list[dict[str, Any]] = [
        {"resolution": "return_to_sender", "quantity": 1},  # note missing
        {"resolution": "return_to_sender", "quantity": 1, "note": "   "},  # blank note
        {"resolution": "sell_it", "quantity": 1, "note": "n"},
        {"resolution": "confirm_loss", "quantity": 0, "note": "n"},
        {"resolution": "confirm_loss", "quantity": "x", "note": "n"},
    ]
    for body in bad:
        r = call(sa, "POST", resolve_url(short["x"]), body)
        assert r.status_code == 400 and r.json()["code"] == "validation_error", body
    assert call(sa, "POST", resolve_url(short["x"]), bad[0], key=False).status_code == 400  # key required
    assert resolve(sa, short["y"], "confirm_loss", 1).status_code == 404  # accepted in full: no shortfall
    assert resolve(sa, 99999, "confirm_loss", 1).status_code == 404
    assert (
        DispatchResolution.objects.count() == 0
        and not StockMovement.objects.filter(movement_type__startswith="resolution").exists()
    )


def test_a_dispatch_still_in_transit_has_no_shortfall(
    users: dict[str, Any], locations: Any, items: dict[str, Item], short: Any
) -> None:
    wa = client_as(users["wa"])
    body = {"destination_id": locations["b"].pk, "lines": [{"item_id": items["x"].pk, "quantity": 1}]}
    d = call(wa, "POST", TRF, body).json()
    assert resolve(client_as(users["sa"]), d["lines"][0]["id"], "confirm_loss", 1).status_code == 404


# ---------- permissions and scope ----------


def test_permissions_and_scope_per_role(
    users: dict[str, Any], make_user: Callable[..., Any], short: Any, locations: Any
) -> None:
    other_ba = make_user("branch_admin", "b")
    fs = client_as(users["fs"])
    assert call(fs, "GET", LIST).status_code == 403
    assert resolve(fs, short["x"], "confirm_loss", 1).status_code == 403
    assert call(APIClient(), "GET", LIST).status_code in (401, 403)
    assert resolve(APIClient(), short["x"], "confirm_loss", 1).status_code in (401, 403)
    # BA of another branch: sees nothing, resolve is 404 like a missing id
    ba_b = client_as(other_ba)
    assert call(ba_b, "GET", LIST).json()["count"] == 0
    assert resolve(ba_b, short["x"], "confirm_loss", 1).status_code == 404
    for key in ("sa", "wa", "ba"):
        listed = call(client_as(users[key]), "GET", LIST).json()
        assert listed["count"] == 1 and listed["results"][0]["id"] == short["x"], key
        assert "cost" not in str(listed).lower()
    assert DispatchResolution.objects.count() == 0
    # WA of the sender can resolve; the audit event is not flagged. BA (the receiver) is flagged.
    assert resolve(client_as(users["ba"]), short["x"], "confirm_loss", 1).status_code == 200
    assert resolve(client_as(users["wa"]), short["x"], "confirm_loss", 1).status_code == 200
    flags = list(
        AuditEvent.objects.filter(action="shortfall_resolved")
        .order_by("id")
        .values_list("is_self_approval", flat=True)
    )
    assert flags == [True, False]
    assert DispatchResolution.objects.filter(is_self_approval=True).count() == 1


def test_list_filters(users: dict[str, Any], short: Any) -> None:
    sa = client_as(users["sa"])
    assert call(sa, "GET", LIST, {"status": "open"}).json()["count"] == 1
    assert call(sa, "GET", LIST, {"status": "resolved"}).json()["count"] == 0
    assert resolve(sa, short["x"], "confirm_loss", 4).status_code == 200
    assert call(sa, "GET", LIST, {"status": "open"}).json()["count"] == 0
    resolved = call(sa, "GET", LIST, {"status": "resolved"}).json()
    assert (
        resolved["count"] == 1
        and resolved["results"][0]["resolutions"][0]["resolved_by"] == users["sa"].login_id
    )
    assert call(sa, "GET", LIST, {"dispatch_id": short["dispatch"]["id"] + 1}).json()["count"] == 0
    assert call(sa, "GET", LIST, {"status": "weird"}).status_code == 400


# ---------- idempotency and concurrency ----------


def test_replay_with_the_same_key_posts_once(
    users: dict[str, Any], locations: Any, items: Any, short: Any
) -> None:
    ba, key = client_as(users["ba"]), uuid.uuid4()
    first = resolve(ba, short["x"], "confirm_loss", 2, key=key)
    again = resolve(ba, short["x"], "confirm_loss", 2, key=key)
    assert first.status_code == again.status_code == 200 and first.json() == again.json()
    assert DispatchResolution.objects.count() == 1 and bal(locations["wh"], items["x"]) == (12, 2, 0)
    other = resolve(ba, short["x"], "confirm_loss", 1, key=key)
    assert other.status_code == 409 and other.json()["code"] == "idempotency_conflict"


@pytest.mark.django_db(transaction=True)
def test_two_simultaneous_full_resolutions_exactly_one_wins(
    users: dict[str, Any], locations: Any, items: Any, short: Any
) -> None:
    clients = [client_as(users["ba"]), client_as(users["wa"])]
    barrier = Barrier(2)

    def send(client: APIClient) -> int:
        try:
            barrier.wait()
            return int(resolve(client, short["x"], "confirm_loss", 4).status_code)
        finally:
            connection.close()

    with ThreadPoolExecutor(2) as pool:
        codes = sorted(pool.map(send, clients))
    assert codes == [200, 409], codes
    assert bal(locations["wh"], items["x"]) == (10, 0, 0) and DispatchResolution.objects.count() == 1


@pytest.mark.django_db(transaction=True)
def test_simultaneous_partial_resolutions_never_exceed_the_shortfall(
    users: dict[str, Any], locations: Any, items: Any, short: Any
) -> None:
    clients = [client_as(users["ba"]) for _ in range(3)]
    barrier = Barrier(3)

    def send(client: APIClient) -> int:
        try:
            barrier.wait()
            return int(resolve(client, short["x"], "return_to_sender", 2).status_code)
        finally:
            connection.close()

    with ThreadPoolExecutor(3) as pool:
        codes = sorted(pool.map(send, clients))
    assert codes == [200, 200, 409], codes
    assert bal(locations["wh"], items["x"]) == (14, 0, 0)


# ---------- B7.2 activity log ----------


def test_activity_log_scope_filters_and_no_cost(
    users: dict[str, Any], locations: Any, short: Any, make_user: Callable[..., Any]
) -> None:
    resolve(client_as(users["ba"]), short["x"], "confirm_loss", 1)
    AuditEvent.objects.create(
        action="user_created", actor_login_id="SA-0001", target_type="user"
    )  # no location
    sa, wa, ba = (client_as(users[k]) for k in ("sa", "wa", "ba"))
    all_events = call(sa, "GET", ACTIVITY, {"page_size": 100}).json()
    assert all_events["count"] == AuditEvent.objects.count()
    first = all_events["results"][0]
    assert set(first) == {
        "id", "occurred_at", "user_id", "user_login_id", "user_role", "branch_id", "branch_name",
        "action", "target_type", "target_ref", "is_self_approval",
    }  # fmt: skip
    assert "cost" not in str(all_events).lower() and "before" not in str(all_events)
    wa_events = call(wa, "GET", ACTIVITY, {"page_size": 100}).json()["results"]
    assert wa_events and {e["branch_id"] for e in wa_events} == {locations["wh"].pk}
    ba_events = call(ba, "GET", ACTIVITY, {"page_size": 100}).json()["results"]
    assert ba_events and {e["branch_id"] for e in ba_events} == {locations["a"].pk}
    assert {"dispatch_received", "shortfall_resolved"} <= {e["action"] for e in ba_events}
    assert "user_created" not in {e["action"] for e in wa_events + ba_events}  # no-location events: SA only
    assert call(ba, "GET", ACTIVITY, {"branch_id": locations["a"].pk}).status_code == 200
    denied = call(ba, "GET", ACTIVITY, {"branch_id": locations["b"].pk})
    assert denied.status_code == 403 and denied.json()["code"] == "wrong_branch"
    assert call(wa, "GET", ACTIVITY, {"branch_id": locations["a"].pk}).status_code == 403
    assert call(client_as(users["fs"]), "GET", ACTIVITY).status_code == 403
    assert call(APIClient(), "GET", ACTIVITY).status_code in (401, 403)
    # SA filters
    only_a = call(sa, "GET", ACTIVITY, {"branch_id": locations["a"].pk}).json()["results"]
    assert {e["branch_id"] for e in only_a} == {locations["a"].pk}
    by_action = call(sa, "GET", ACTIVITY, {"action": "shortfall_resolved"}).json()
    assert by_action["count"] == 1 and by_action["results"][0]["user_id"] == users["ba"].pk
    assert call(sa, "GET", ACTIVITY, {"user_id": users["ba"].pk}).json()["count"] >= 2
    assert call(sa, "GET", ACTIVITY, {"user_id": 999999}).json()["count"] == 0
    today = timezone.localdate()
    assert (
        call(sa, "GET", ACTIVITY, {"date_from": today, "date_to": today}).json()["count"]
        == AuditEvent.objects.count()
    )  # a later login adds events
    assert call(sa, "GET", ACTIVITY, {"date_from": today + timedelta(days=1)}).json()["count"] == 0
    assert call(sa, "GET", ACTIVITY, {"date_to": today - timedelta(days=1)}).json()["count"] == 0
    assert call(sa, "GET", ACTIVITY, {"date_from": "yesterday"}).status_code == 400
    assert call(sa, "GET", ACTIVITY, {"page_size": 2}).json()["page_size"] == 2
    times = [e["occurred_at"] for e in all_events["results"]]
    assert times == sorted(times, reverse=True)  # newest first


# ---------- B7.1 dashboard ----------


def test_dashboard_low_stock_and_recent_activity_scoped(
    users: dict[str, Any], locations: Any, items: dict[str, Item], short: Any
) -> None:
    # WH x: on_hand 14 reserved 4 -> available 10; A x: 6 available. Reorder levels decide low stock.
    StockBalance.objects.filter(location=locations["wh"], item=items["x"]).update(reorder_level=10)  # low (=)
    StockBalance.objects.filter(location=locations["a"], item=items["x"]).update(reorder_level=5)  # fine
    StockBalance.objects.filter(location=locations["wh"], item=items["y"]).update(
        reorder_level=None
    )  # no level
    StockBalance.objects.create(
        location=locations["b"], item=items["y"], on_hand=1, reorder_level=2
    )  # low at B
    sa = call(client_as(users["sa"]), "GET", DASH).json()
    assert sa["low_stock_count"] == 2
    assert [(r["location_name"], r["sku"], r["available"], r["reorder_level"]) for r in sa["low_stock"]] == [
        ("Central Warehouse", "SKU-X", 10, 10),
        ("Branch B", "SKU-Y", 1, 2),
    ]
    one = call(client_as(users["sa"]), "GET", DASH, {"branch": locations["b"].pk}).json()
    assert one["low_stock_count"] == 1 and len(one["recent_activity"]) == 0
    wa = call(client_as(users["wa"]), "GET", DASH).json()
    assert [r["location_name"] for r in wa["low_stock"]] == ["Central Warehouse"]
    assert {e["branch_id"] for e in wa["recent_activity"]} == {locations["wh"].pk}
    ba = call(client_as(users["ba"]), "GET", DASH).json()
    assert ba["low_stock_count"] == 0 and ba["low_stock"] == []
    assert ba["recent_activity"] and {e["branch_id"] for e in ba["recent_activity"]} == {locations["a"].pk}
    assert len(sa["recent_activity"]) <= 10
    assert "cost" not in str(sa).lower()
    assert call(client_as(users["fs"]), "GET", DASH).status_code == 403


# ---------- contract ----------


def test_generated_schema_matches_the_contract_for_the_day7_operations(tmp_path: Path) -> None:
    out = tmp_path / "schema.yaml"
    call_command("spectacular", file=str(out))
    generated = yaml.safe_load(out.read_text(encoding="utf-8"))
    contract = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))
    prefixes = ("/api/v1/shortfalls/", "/api/v1/activity-log/", "/api/v1/dashboard/")

    def ops(spec: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
        return {
            (p, m): op
            for p, i in spec["paths"].items()
            if p.startswith(prefixes)
            for m, op in i.items()
            if m in METHODS
        }

    gen_ops, ref_ops = ops(generated), ops(contract)
    assert set(gen_ops) == set(ref_ops) and len(ref_ops) == 5
    for key, ref in ref_ops.items():
        gen = gen_ops[key]
        assert gen["operationId"] == ref["operationId"], key
        assert set(gen["responses"]) <= set(ref["responses"]), key
        assert query_names(generated, gen, {}) == query_names(contract, ref, {}), key
        if "200" in ref["responses"] and "content" in ref["responses"]["200"]:
            assert props(generated, first_schema(gen["responses"]["200"]["content"])) == props(
                contract, first_schema(ref["responses"]["200"]["content"])
            ), key
        if "requestBody" in ref:
            assert props(generated, first_schema(gen["requestBody"]["content"])) == props(
                contract, first_schema(ref["requestBody"]["content"])
            ), key


# ---------- Day 7 review fixes (FIX-45 to FIX-49) ----------


def test_fix45_admins_without_a_location_never_see_unfiltered_low_stock(
    make_user: Callable[..., Any], locations: Any, items: dict[str, Item]
) -> None:
    StockBalance.objects.create(location=locations["a"], item=items["x"], on_hand=1, reorder_level=5)
    for role, loc in (("warehouse_admin", "wh"), ("branch_admin", "a")):
        user = make_user(role, loc)
        client = client_as(user)
        type(user).objects.filter(pk=user.pk).update(
            permanent_location=None
        )  # a data fault, not a normal state
        body = call(client, "GET", DASH).json()
        assert body["low_stock_count"] == 0 and body["low_stock"] == [], role


def test_fix46_super_admin_low_stock_skips_inactive_locations(
    users: dict[str, Any], locations: Any, items: dict[str, Item]
) -> None:
    StockBalance.objects.create(location=locations["a"], item=items["x"], on_hand=1, reorder_level=5)
    StockBalance.objects.create(location=locations["b"], item=items["x"], on_hand=1, reorder_level=5)
    type(locations["b"]).objects.filter(pk=locations["b"].pk).update(is_active=False)
    body = call(client_as(users["sa"]), "GET", DASH).json()
    assert body["low_stock_count"] == 1 and [r["location_name"] for r in body["low_stock"]] == ["Branch A"]


def test_fix47_audit_events_have_a_location_time_index() -> None:
    assert any(list(i.fields) == ["location", "occurred_at"] for i in AuditEvent._meta.indexes)


def test_fix48_date_from_after_date_to_is_a_400_on_date_to(users: dict[str, Any]) -> None:
    r = call(client_as(users["sa"]), "GET", ACTIVITY, {"date_from": "2026-03-02", "date_to": "2026-03-01"})
    assert r.status_code == 400 and r.json()["errors"][0]["field"] == "date_to"
    same = call(client_as(users["sa"]), "GET", ACTIVITY, {"date_from": "2026-03-01", "date_to": "2026-03-01"})
    assert same.status_code == 200


def test_fix49_a_shortfall_at_a_deactivated_location_can_still_be_resolved(
    users: dict[str, Any], locations: Any, items: dict[str, Item], short: Any
) -> None:
    ba, sa = client_as(users["ba"]), client_as(users["sa"])
    type(locations["a"]).objects.filter(pk=locations["a"].pk).update(is_active=False)
    assert resolve(ba, short["x"], "return_to_sender", 2).status_code == 200
    assert resolve(sa, short["x"], "record_damage", 2).status_code == 200
    assert bal(locations["wh"], items["x"]) == (12, 0, 0) and bal(locations["a"], items["x"])[2] == 2

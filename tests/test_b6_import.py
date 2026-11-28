"""B6.4, B6.6: CSV import of items and opening quantities. Role matrix, dry run, error report with row
numbers, opening balances as ledger movements, unit cost folded into the average cost before the stock
is posted, all-or-nothing commit, idempotency."""

import uuid
from decimal import Decimal
from typing import Any

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from audit.models import AuditEvent
from config.errors import ApiError
from inventory import imports
from inventory.models import Brand, ImportBatch, Item, ItemCost, ItemPrice, ItemStatus, StockBalance
from roles import constants as c
from roles.models import UserPermission
from stock_ledger.models import SourceType, StockMovement
from tests.api import client_as

URL = "/api/v1/item-imports/"
HEADER = "sku,name,category,subtype,brand,model_name,mpn,condition,opening_quantity,unit_cost"
GOOD = (
    f"{HEADER}\n"
    ",HP 250 G9,Laptop,Business,HP,250 G9,MPN-1,new,10,1200.50\n"
    ",HP Charger,Accessory,Laptop chargers,HP,65W,MPN-2,used,4,15.00\n"
)


@pytest.fixture(autouse=True)
def reference_brand(locations: Any) -> None:
    Brand.objects.create(name="HP")


def csv_file(text: str, name: str = "stock.csv") -> SimpleUploadedFile:
    return SimpleUploadedFile(name, text.encode("utf-8"), content_type="text/csv")


def send(
    client: APIClient, text: str | bytes, *, dry_run: bool = True, location: Any = None, **kw: Any
) -> Any:
    raw = text if isinstance(text, bytes) else text.encode("utf-8")
    data: dict[str, Any] = {
        "file": SimpleUploadedFile("stock.csv", raw),
        "dry_run": "true" if dry_run else "false",
    }
    if location is not None:
        data["location_id"] = location.pk
    data.update(kw.pop("extra", {}))
    key = kw.pop("key", None)
    return client.post(URL, data, format="multipart", HTTP_IDEMPOTENCY_KEY=str(key or uuid.uuid4()))


def nothing_written() -> bool:
    return not (
        Item.objects.exists()
        or ItemCost.objects.exists()
        or StockMovement.objects.exists()
        or ImportBatch.objects.exists()
        or AuditEvent.objects.filter(action__in=["csv_import_committed", "item_created"]).exists()
    )


@pytest.fixture
def wa(users: dict[str, Any]) -> APIClient:
    return client_as(users["wa"])


@pytest.fixture
def sa(users: dict[str, Any]) -> APIClient:
    return client_as(users["sa"])


# ---------- permissions ----------


@pytest.mark.parametrize(("role", "ok"), [("sa", True), ("wa", True), ("ba", False), ("fs", False)])
def test_only_super_admin_and_warehouse_admin_can_import(
    role: str, ok: bool, users: dict[str, Any], locations: Any
) -> None:
    response = send(client_as(users[role]), GOOD, location=locations["wh"])
    if ok:
        assert response.status_code == 200, response.content
    else:
        assert response.status_code == 403 and response.json()["code"] == "permission_denied"
    assert nothing_written()


def test_anonymous_gets_401(locations: Any) -> None:
    assert send(APIClient(), GOOD, location=locations["wh"]).status_code == 401


def test_warehouse_admin_cannot_load_another_location(wa: APIClient, locations: Any) -> None:
    response = send(wa, GOOD, dry_run=False, location=locations["a"])
    assert response.status_code == 403 and response.json()["code"] == "wrong_branch"
    assert nothing_written()


def test_super_admin_must_name_the_location_and_it_must_be_active(sa: APIClient, locations: Any) -> None:
    missing = send(sa, GOOD)
    assert missing.status_code == 400 and missing.json()["errors"][0]["field"] == "location_id"
    locations["a"].is_active = False
    locations["a"].save()
    assert send(sa, GOOD, location=locations["a"]).status_code == 400
    assert send(sa, GOOD, extra={"location_id": 999999}).status_code == 400
    assert nothing_written()


# ---------- dry run ----------


def test_dry_run_reports_and_writes_nothing(wa: APIClient, locations: Any) -> None:
    response = send(wa, GOOD, dry_run=True)
    assert response.status_code == 200, response.content
    assert response.json() == {
        "dry_run": True,
        "committed": False,
        "batch_reference": None,
        "location_id": locations["wh"].pk,
        "rows": 2,
        "items_created": 2,
        "items_existing": 0,
        "opening_quantity_total": 14,
        "errors": [],
    }
    assert nothing_written()
    assert not StockBalance.objects.exists()


def test_dry_run_must_be_stated_so_a_missing_value_never_commits(wa: APIClient) -> None:
    for extra in ({}, {"dry_run": "maybe"}):
        data: dict[str, Any] = {"file": csv_file(GOOD)}
        data.update(extra)
        response = wa.post(URL, data, format="multipart", HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()))
        assert response.status_code == 400 and response.json()["errors"][0]["field"] == "dry_run"
    assert nothing_written()


# ---------- commit ----------


def test_commit_creates_items_cost_balances_ledger_batch_and_audit(
    wa: APIClient, users: dict[str, Any], locations: Any
) -> None:
    response = send(wa, GOOD, dry_run=False)
    assert response.status_code == 200, response.content
    report = response.json()
    batch = ImportBatch.objects.get()
    assert report["committed"] and report["batch_reference"] == batch.reference == "IMP-000001"
    assert (batch.location_id, batch.row_count, batch.file_name) == (locations["wh"].pk, 2, "stock.csv")
    assert batch.imported_by_id == users["wa"].pk
    laptop, charger = Item.objects.order_by("id")
    assert laptop.status == ItemStatus.DRAFT and laptop.sku.startswith("SKU-") and laptop.condition == "new"
    assert laptop.category.name == "Laptop" and charger.condition == "used"
    assert laptop.subtype is not None and laptop.subtype.name == "Business"
    assert ItemCost.objects.get(item=laptop).average_cost == Decimal("1200.5000")
    assert ItemCost.objects.get(item=charger).average_cost == Decimal("15.0000")
    assert [(b.item_id, b.on_hand, b.reserved) for b in StockBalance.objects.order_by("item_id")] == [
        (laptop.pk, 10, 0),
        (charger.pk, 4, 0),
    ]
    moves = list(StockMovement.objects.order_by("id"))
    assert [(m.item_id, m.bucket, m.quantity_delta, m.balance_after) for m in moves] == [
        (laptop.pk, "on_hand", 10, 10),
        (charger.pk, "on_hand", 4, 4),
    ]
    for move, row in zip(moves, (2, 3), strict=True):  # the CSV row number is the ledger line id
        assert (move.movement_type, move.source_type, move.source_id, move.source_line_id) == (
            "opening_balance",
            SourceType.CSV_IMPORT,
            batch.pk,
            row,
        )
        assert move.source_ref == batch.reference and move.location_id == locations["wh"].pk
        assert move.actor_id == users["wa"].pk
    event = AuditEvent.objects.get(action="csv_import_committed")
    assert event.target_ref == batch.reference
    assert event.after_values == {"rows": 2, "items_created": 2, "opening_quantity_total": 14}
    assert AuditEvent.objects.filter(action="item_created").count() == 2
    assert "1200" not in str(event.after_values)  # no cost in the audit trail


def test_the_cost_row_exists_before_the_stock_is_posted(
    wa: APIClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[tuple[int, int]] = []
    real = imports.post_stock_changes

    def spy(changes: Any, **kwargs: Any) -> Any:
        seen.append((ItemCost.objects.count(), len(changes)))
        return real(changes, **kwargs)

    monkeypatch.setattr(imports, "post_stock_changes", spy)
    assert send(wa, GOOD, dry_run=False).status_code == 200
    assert seen == [(2, 2)]


def test_unit_cost_folds_into_the_average_cost_of_an_existing_item(
    wa: APIClient, users: dict[str, Any], locations: Any
) -> None:
    assert (
        send(wa, f"{HEADER}\n,Cable,Accessory,Mice,HP,C1,M1,new,10,100.00\n", dry_run=False).status_code
        == 200
    )
    item = Item.objects.get()
    again = f"sku,opening_quantity,unit_cost\n{item.sku.lower()},10,200.00\n"  # an existing SKU, any case
    report = send(wa, again, dry_run=False).json()
    assert report["committed"] and report["items_existing"] == 1 and report["items_created"] == 0
    assert ItemCost.objects.get(item=item).average_cost == Decimal("150.0000")
    assert StockBalance.objects.get(item=item).on_hand == 20
    assert Item.objects.count() == 1 and ImportBatch.objects.count() == 2


def test_an_existing_item_with_stock_elsewhere_folds_that_stock_in(
    sa: APIClient, users: dict[str, Any], locations: Any
) -> None:
    assert (
        send(
            sa,
            f"{HEADER}\n,Cable,Accessory,Mice,HP,C1,M1,new,10,100.00\n",
            dry_run=False,
            location=locations["wh"],
        ).status_code
        == 200
    )
    item = Item.objects.get()
    report = send(
        sa, f"sku,opening_quantity,unit_cost\n{item.sku},30,200.00\n", dry_run=False, location=locations["a"]
    ).json()
    assert report["committed"] and report["location_id"] == locations["a"].pk
    assert ItemCost.objects.get(item=item).average_cost == Decimal("175.0000")  # (10*100 + 30*200) / 40
    assert StockBalance.objects.get(item=item, location=locations["a"]).on_hand == 30
    assert StockBalance.objects.get(item=item, location=locations["wh"]).on_hand == 10


def test_zero_quantity_creates_the_item_but_no_stock_and_no_ledger_row(wa: APIClient) -> None:
    report = send(wa, f"{HEADER}\n,Cable,Accessory,Mice,HP,C1,M1,new,0,9.99\n", dry_run=False).json()
    assert report["committed"] and Item.objects.count() == 1
    assert not StockMovement.objects.exists() and not ItemCost.objects.exists()


def test_reorder_level_bin_label_and_price(sa: APIClient, locations: Any) -> None:
    text = (
        f"{HEADER},selling_price,reorder_level,bin_label\n"
        ",Cable,Accessory,Mice,HP,C1,M1,new,5,2.00,9.50,3,A-12\n"
        ",Mouse,Accessory,Mice,HP,C2,M2,new,0,1.00,,,\n"
    )
    report = send(sa, text, dry_run=False, location=locations["wh"]).json()
    assert report["committed"], report
    cable = Item.objects.get(name="Cable")
    balance = StockBalance.objects.get(item=cable)
    assert (balance.on_hand, balance.reorder_level, balance.bin_label) == (5, 3, "A-12")
    assert ItemPrice.objects.get(item=cable).selling_price == Decimal("9.50")
    assert not ItemPrice.objects.filter(item__name="Mouse").exists()


def test_a_bin_label_belongs_to_a_warehouse_row(sa: APIClient, locations: Any) -> None:
    text = f"{HEADER},bin_label\n,Cable,Accessory,Mice,HP,C1,M1,new,5,2.00,A-12\n"
    report = send(sa, text, dry_run=False, location=locations["a"]).json()
    assert not report["committed"] and report["errors"][0]["field"] == "bin_label"
    assert nothing_written()


def test_setting_a_price_needs_the_manage_prices_right(wa: APIClient, users: dict[str, Any]) -> None:
    text = f"{HEADER},selling_price\n,Cable,Accessory,Mice,HP,C1,M1,new,5,2.00,9.50\n"
    report = send(wa, text, dry_run=False).json()
    assert not report["committed"]
    assert report["errors"] == [
        {"row": 2, "field": "selling_price", "message": "You are not allowed to set prices."}
    ]
    assert nothing_written()
    UserPermission.objects.create(user=users["wa"], permission=c.MANAGE_PRICES)
    assert send(wa, text, dry_run=False).json()["committed"]
    assert ItemPrice.objects.get().selling_price == Decimal("9.50")


def test_a_price_on_an_existing_item_is_refused(wa: APIClient, sa: APIClient, locations: Any) -> None:
    assert send(wa, GOOD, dry_run=False).status_code == 200
    sku = Item.objects.order_by("id").first().sku  # type: ignore[union-attr]
    report = send(
        sa, f"sku,opening_quantity,unit_cost,selling_price\n{sku},1,1.00,5.00\n", location=locations["wh"]
    ).json()
    assert report["errors"][0]["field"] == "selling_price"


def test_an_imported_sku_is_kept_unchanged(wa: APIClient) -> None:
    text = f"{HEADER}\nIMP-LAP-1,HP 250 G9,Laptop,Business,HP,250 G9,MPN-1,new,1,1.00\n"
    assert send(wa, text, dry_run=False).json()["committed"]
    assert Item.objects.get().sku == "IMP-LAP-1"


# ---------- error report ----------


def test_every_bad_row_is_reported_with_its_csv_row_number_and_nothing_is_kept(wa: APIClient) -> None:
    text = (
        f"{HEADER}\n"
        ",Good,Laptop,Business,HP,G1,M1,new,5,10.00\n"  # row 2 fine
        ",NoCost,Laptop,Business,HP,G2,M2,new,5,\n"  # row 3: unit cost required
        ",BadQty,Laptop,Business,HP,G3,M3,new,-1,10.00\n"  # row 4
        ",BadBrand,Laptop,Business,Nokia,G4,M4,new,1,10.00\n"  # row 5
        ",BadCat,Phone,Business,HP,G5,M5,new,1,10.00\n"  # row 6
        ",BadSub,Laptop,Tablet,HP,G6,M6,new,1,10.00\n"  # row 7
        ",BadCond,Laptop,Business,HP,G7,M7,broken,1,10.00\n"  # row 8
        ",,Laptop,Business,HP,G8,M8,new,1,10.00\n"  # row 9: name missing
        ",BadCost,Laptop,Business,HP,G9,M9,new,1,1.234\n"  # row 10: 3 decimals
        ",Good2,Laptop,Business,HP,G10,M10,new,2,10.00\n"  # row 11 fine
        "UNKNOWN-SKU,,,,,,,,1,1.00\n"  # row 12: new SKU but item columns missing
    )
    for dry_run in (True, False):  # a commit with errors behaves like a dry run: nothing is kept
        report = send(wa, text, dry_run=dry_run).json()
        assert report["committed"] is False and report["batch_reference"] is None and report["rows"] == 11
        assert [(e["row"], e["field"]) for e in report["errors"]] == [
            (3, "unit_cost"),
            (4, "opening_quantity"),
            (5, "brand"),
            (6, "category"),
            (7, "subtype"),
            (8, "condition"),
            (9, "name"),
            (10, "unit_cost"),
            (12, "name"),
        ]
        assert all(e["message"] for e in report["errors"])
        assert (
            report["items_created"] == 2 and report["opening_quantity_total"] == 7
        )  # the good rows, planned only
        assert nothing_written()


def test_a_sku_twice_in_one_file_is_an_error_on_the_second_row(wa: APIClient) -> None:
    row = "DUP-1,{},Laptop,Business,HP,{},M1,new,1,1.00\n"
    text = f"{HEADER}\n" + row.format("A", "G1") + row.format("B", "G2")
    report = send(wa, text, dry_run=False).json()
    assert [(e["row"], e["field"]) for e in report["errors"]] == [(3, "sku")] and not report["committed"]
    assert nothing_written()


def test_a_discontinued_item_cannot_receive_opening_stock(wa: APIClient) -> None:
    assert send(wa, GOOD, dry_run=False).json()["committed"]
    item = Item.objects.order_by("id").first()
    assert item is not None
    Item.objects.filter(pk=item.pk).update(status=ItemStatus.DISCONTINUED)
    report = send(wa, f"sku,opening_quantity,unit_cost\n{item.sku},1,1.00\n").json()
    assert report["errors"][0]["row"] == 2 and report["errors"][0]["field"] == "sku"


def test_too_long_values_are_row_errors_not_server_errors(wa: APIClient) -> None:
    text = f"{HEADER}\n,{'N' * 201},Laptop,Business,HP,G1,M1,new,1,1.00\n"
    report = send(wa, text).json()
    assert report["errors"][0] == {"row": 2, "field": "name", "message": "Use at most 200 characters."}


# ---------- file level errors ----------


@pytest.mark.parametrize(
    ("raw", "needle"),
    [
        (b"", "empty"),
        (f"{HEADER}\n".encode(), "no data rows"),
        (b"name,opening_quantity\nA,1\n", "unit_cost"),
        (f"{HEADER},colour\n,A,Laptop,Business,HP,G,M,new,1,1.00,red\n".encode(), "colour"),
        (b"\xff\xfe\x00bad", "UTF-8"),
    ],
)
def test_file_level_problems_are_400_with_the_file_field(raw: bytes, needle: str, wa: APIClient) -> None:
    response = send(wa, raw, dry_run=False)
    assert response.status_code == 400 and response.json()["errors"][0]["field"] == "file"
    assert needle in str(response.json())
    assert nothing_written()


def test_a_missing_file_is_400(wa: APIClient) -> None:
    response = wa.post(URL, {"dry_run": "true"}, format="multipart", HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()))
    assert response.status_code == 400 and response.json()["errors"][0]["field"] == "file"


def test_size_and_row_limits(wa: APIClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(imports, "MAX_BYTES", 50)
    response = send(wa, GOOD)
    assert response.status_code == 413 and response.json()["code"] == "file_too_large"
    monkeypatch.setattr(imports, "MAX_BYTES", 2 * 1024 * 1024)
    monkeypatch.setattr(imports, "MAX_ROWS", 1)
    response = send(wa, GOOD)
    assert response.status_code == 400 and "At most 1 rows" in response.json()["message"]
    assert nothing_written()


def test_blank_lines_are_skipped_and_a_bom_is_accepted(wa: APIClient) -> None:
    text = "﻿" + GOOD.replace("\n", "\n\n", 1)
    report = send(wa, text.encode("utf-8")).json()
    assert report["rows"] == 2 and report["errors"] == []


# ---------- atomicity, idempotency ----------


def test_a_stock_failure_after_the_rows_passed_leaves_nothing_behind(
    wa: APIClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*args: Any, **kwargs: Any) -> Any:
        raise ApiError(409, "conflict", "This stock change has already been posted.")

    monkeypatch.setattr(imports, "post_stock_changes", boom)
    response = send(wa, GOOD, dry_run=False)
    assert response.status_code == 409
    assert nothing_written()


def test_commit_never_reuses_a_batch_reference_created_outside_the_sequence(
    wa: APIClient, users: dict[str, Any], locations: Any
) -> None:
    """Seed data and restores create batches outside the IMP sequence: the next import must not collide."""
    ImportBatch.objects.create(
        reference="IMP-000003",
        location=locations["wh"],
        file_name="seed",
        row_count=1,
        imported_by=users["wa"],
        operation_id=uuid.uuid4(),
    )
    response = send(wa, GOOD, dry_run=False)
    assert response.status_code == 200, response.content
    assert response.json()["batch_reference"] == "IMP-000004"


def test_replaying_a_commit_with_the_same_key_imports_once(wa: APIClient) -> None:
    key = uuid.uuid4()
    first, again = send(wa, GOOD, dry_run=False, key=key), send(wa, GOOD, dry_run=False, key=key)
    assert first.status_code == again.status_code == 200 and first.json() == again.json()
    assert (
        ImportBatch.objects.count() == 1 and Item.objects.count() == 2 and StockMovement.objects.count() == 2
    )
    other = send(wa, GOOD.replace("10,1200.50", "11,1200.50"), dry_run=False, key=key)
    assert other.status_code == 409 and other.json()["code"] == "idempotency_conflict"


def test_the_same_batch_row_can_never_post_twice(wa: APIClient) -> None:
    from stock_ledger.models import Bucket, MovementType
    from stock_ledger.services import StockChange, post_stock_changes

    assert send(wa, GOOD, dry_run=False).status_code == 200
    move = StockMovement.objects.order_by("id").first()
    assert move is not None
    change = StockChange(
        move.location,
        move.item,
        Bucket.ON_HAND,
        4,
        MovementType.OPENING_BALANCE,
        SourceType.CSV_IMPORT,
        move.source_id,
        move.source_line_id,
    )
    with pytest.raises(ApiError) as caught:
        post_stock_changes([change], actor=None)  # a fresh operation, the same batch row
    assert caught.value.code == "conflict"
    assert (
        StockMovement.objects.filter(source_id=move.source_id, source_line_id=move.source_line_id).count()
        == 1
    )

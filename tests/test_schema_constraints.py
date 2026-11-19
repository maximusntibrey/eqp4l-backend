"""B2.1: the database constraints of the approved ERD reject bad data (ERD s9).

Every test writes one row that breaks exactly one rule and expects the database (not Python
validation) to refuse it. A good row for the same shape is accepted, so a rejection is the
constraint and not a typo in the test data.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from decimal import Decimal as D

import pytest
from django.db import DatabaseError, IntegrityError, connection, transaction
from django.utils import timezone

from accounts.models import User
from inventory.models import Item, Price, StockBalance
from roles.models import PermissionCode, Role, UserPermissionGrant, UserRole
from sales.models import PaymentMethod, Sale, SaleLine
from stock_ledger.models import Entry
from tests.factories import make_branch, make_item, make_operation, make_user
from transfers.models import (
    Discrepancy,
    DiscrepancyResolution,
    Dispatch,
    DispatchLine,
)
from warehouse.models import GoodsReceipt, GoodsReceiptLine

pytestmark = pytest.mark.django_db


@contextmanager
def rejected(error: type[DatabaseError] = IntegrityError) -> Iterator[None]:
    """The block must be refused by the database (inside a savepoint)."""
    with pytest.raises(error), transaction.atomic():
        yield


# --- accounts --------------------------------------------------------------------------


@pytest.mark.parametrize("login_id", ["", "ABC-0001", "SA-1", "USR-12", "usr-0001", "SA-00A1"])
def test_user_login_id_format_is_enforced(login_id: str) -> None:
    with rejected():
        User.objects.create(login_id=login_id, full_name="A", phone="1", status="active")


@pytest.mark.parametrize("login_id", ["SA-0001", "USR-0001", "USR-12345"])
def test_user_login_id_valid_formats_are_accepted(login_id: str) -> None:
    User.objects.create(login_id=login_id, full_name="A", phone="1", status="active")


def test_user_status_must_be_known() -> None:
    with rejected():
        make_user(status="retired")


def test_user_login_id_is_unique() -> None:
    make_user(login_id="USR-8001")
    with rejected():
        make_user(login_id="USR-8001")


def test_user_email_is_optional_but_name_and_phone_are_required() -> None:
    assert make_user(email=None).email is None
    with rejected():
        make_user(full_name=None)
    with rejected():
        make_user(phone=None)


def test_user_must_change_password_defaults_to_false() -> None:
    assert make_user().must_change_password is False


# --- roles -----------------------------------------------------------------------------


def test_four_roles_are_seeded() -> None:
    assert set(Role.objects.values_list("code", flat=True)) == {
        "super_admin",
        "warehouse_admin",
        "branch_admin",
        "front_staff",
    }


def test_role_code_must_be_known() -> None:
    with rejected():
        Role.objects.create(code="owner", name="Owner")


def test_user_has_one_active_row_per_role_but_history_is_kept() -> None:
    user, admin = make_user(), make_user()
    role = Role.objects.get(code="branch_admin")
    first = UserRole.objects.create(
        user=user, role=role, assigned_by=admin, assigned_at=timezone.now()
    )
    with rejected():
        UserRole.objects.create(user=user, role=role, assigned_by=admin, assigned_at=timezone.now())
    first.revoked_by, first.revoked_at = admin, timezone.now()
    first.save()
    UserRole.objects.create(user=user, role=role, assigned_by=admin, assigned_at=timezone.now())


def test_role_revocation_needs_both_who_and_when() -> None:
    user, admin = make_user(), make_user()
    role = Role.objects.get(code="front_staff")
    with rejected():
        UserRole.objects.create(
            user=user,
            role=role,
            assigned_by=admin,
            assigned_at=timezone.now(),
            revoked_at=timezone.now(),
        )
    with rejected():
        UserRole.objects.create(
            user=user, role=role, assigned_by=admin, assigned_at=timezone.now(), revoked_by=admin
        )


def test_permission_grant_must_be_known_and_unique_while_active() -> None:
    user, admin = make_user(), make_user()
    with rejected():
        UserPermissionGrant.objects.create(
            user=user, permission="superpower", granted_by=admin, granted_at=timezone.now()
        )
    UserPermissionGrant.objects.create(
        user=user,
        permission=PermissionCode.MANAGE_PRICES,
        granted_by=admin,
        granted_at=timezone.now(),
    )
    with rejected():
        UserPermissionGrant.objects.create(
            user=user,
            permission=PermissionCode.MANAGE_PRICES,
            granted_by=admin,
            granted_at=timezone.now(),
        )
    with rejected():
        UserPermissionGrant.objects.create(
            user=user,
            permission=PermissionCode.APPLY_DISCOUNT,
            granted_by=admin,
            granted_at=timezone.now(),
            revoked_at=timezone.now(),
        )


# --- branches --------------------------------------------------------------------------


def test_only_one_central_warehouse_can_exist() -> None:
    make_branch(kind="warehouse")
    with rejected():
        make_branch(kind="warehouse")
    make_branch(kind="branch")
    make_branch(kind="branch")


def test_branch_name_is_unique_ignoring_case() -> None:
    make_branch(name="Accra Mall")
    with rejected():
        make_branch(name="ACCRA mall")


@pytest.mark.parametrize("field", ["kind", "status"])
def test_branch_enumerations_are_enforced(field: str) -> None:
    with rejected():
        make_branch(**{field: "other"})


def test_branch_code_is_unique() -> None:
    make_branch(code="BR-900")
    with rejected():
        make_branch(code="BR-900")


# --- inventory -------------------------------------------------------------------------


@pytest.mark.parametrize("field", ["category", "condition", "status"])
def test_item_enumerations_are_enforced(field: str) -> None:
    with rejected():
        make_item(**{field: "other"})


def test_item_sku_is_unique() -> None:
    make_item(sku="SKU-DUP")
    with rejected():
        make_item(sku="SKU-DUP")


def test_item_has_no_price_or_cost_column() -> None:
    names = {f.name for f in Item._meta.get_fields()}
    assert not {"price", "cost", "unit_cost", "selling_price"} & names


def test_item_defaults() -> None:
    item = make_item()
    assert (item.status, item.uom, item.specs, item.show_on_website) == (
        "draft",
        "piece",
        {},
        False,
    )


@pytest.mark.parametrize(
    "values",
    [
        {"on_hand": D("-1")},
        {"reserved": D("-1")},
        {"quarantined": D("-0.001")},
        {"on_hand": D("5"), "reserved": D("6")},
        {"reorder_level": D("-1")},
    ],
)
def test_stock_balance_buckets_are_never_negative_and_reserved_fits_on_hand(
    values: dict[str, D],
) -> None:
    with rejected():
        StockBalance.objects.create(item=make_item(), location=make_branch(), **values)


def test_stock_balance_accepts_valid_values_and_keeps_three_decimals() -> None:
    row = StockBalance.objects.create(
        item=make_item(),
        location=make_branch(),
        on_hand=D("10.500"),
        reserved=D("10.500"),
        quarantined=D("2"),
        reorder_level=D("0"),
    )
    row.refresh_from_db()
    assert (row.on_hand, row.reserved, row.quarantined) == (D("10.500"), D("10.500"), D("2.000"))


def test_stock_balance_is_one_row_per_item_and_location() -> None:
    item, location = make_item(), make_branch()
    StockBalance.objects.create(item=item, location=location)
    with rejected():
        StockBalance.objects.create(item=item, location=location)


def test_stock_balance_has_no_available_or_in_transit_column() -> None:
    names = {f.name for f in StockBalance._meta.get_fields()}
    assert not {"available", "in_transit"} & names
    assert {"on_hand", "reserved", "quarantined", "reorder_level", "bin_label"} <= names


def test_price_is_never_negative() -> None:
    with rejected():
        Price.objects.create(item=make_item(), amount=D("-0.01"), set_by=make_user())


def test_price_scope_and_branch_must_agree() -> None:
    item, user, branch = make_item(), make_user(), make_branch()
    with rejected():
        Price.objects.create(item=item, scope="central", branch=branch, amount=D(1), set_by=user)
    with rejected():
        Price.objects.create(item=item, scope="branch", branch=None, amount=D(1), set_by=user)
    with rejected():
        Price.objects.create(item=item, scope="regional", amount=D(1), set_by=user)
    Price.objects.create(item=item, scope="branch", branch=branch, amount=D(1), set_by=user)


def test_one_current_central_price_per_sku_but_closed_rows_are_allowed() -> None:
    item, user = make_item(), make_user()
    old = Price.objects.create(item=item, amount=D("100.00"), set_by=user)
    with rejected():
        Price.objects.create(item=item, amount=D("120.00"), set_by=user)
    old.effective_to = timezone.now()
    old.save()
    Price.objects.create(item=item, amount=D("120.00"), set_by=user)
    assert Price.objects.filter(item=item).count() == 2


def test_price_amount_is_two_decimals() -> None:
    price = Price.objects.create(item=make_item(), amount=D("10.005"), set_by=make_user())
    price.refresh_from_db()
    assert price.amount == D("10.01")


# --- warehouse -------------------------------------------------------------------------


def _receipt() -> GoodsReceipt:
    warehouse = make_branch(kind="warehouse")
    user = make_user()
    return GoodsReceipt.objects.create(
        location=warehouse,
        supplier_name="Supplier",
        received_by=user,
        received_at=timezone.now(),
        operation=make_operation(actor=user),
    )


def test_goods_receipt_reference_is_generated_from_the_id() -> None:
    receipt = _receipt()
    receipt.refresh_from_db()
    assert receipt.reference == f"GRN-{receipt.pk:06d}"


def test_goods_receipt_reference_cannot_be_written() -> None:
    receipt = _receipt()
    with rejected(DatabaseError), connection.cursor() as cursor:
        cursor.execute(
            "UPDATE warehouse_goodsreceipt SET reference = 'X' WHERE id = %s", [receipt.pk]
        )


def test_one_receipt_per_operation() -> None:
    receipt = _receipt()
    with rejected():
        GoodsReceipt.objects.create(
            location=receipt.location,
            supplier_name="S",
            received_by=receipt.received_by,
            received_at=timezone.now(),
            operation=receipt.operation,
        )


@pytest.mark.parametrize(
    "values", [{"quantity": D("0")}, {"quantity": D("-1")}, {"unit_cost": D("-0.01")}]
)
def test_receipt_line_quantity_positive_and_cost_not_negative(values: dict[str, D]) -> None:
    receipt = _receipt()
    data = {"quantity": D("1"), "unit_cost": D("10.00"), **values}
    with rejected():
        GoodsReceiptLine.objects.create(receipt=receipt, line_no=1, item=make_item(), **data)


def test_receipt_line_cost_is_mandatory_and_line_no_unique() -> None:
    receipt, item = _receipt(), make_item()
    with rejected():
        GoodsReceiptLine.objects.create(
            receipt=receipt,
            line_no=1,
            item=item,
            quantity=D(1),
            unit_cost=None,  # type: ignore[misc]
        )
    GoodsReceiptLine.objects.create(
        receipt=receipt, line_no=1, item=item, quantity=D(1), unit_cost=D(0)
    )
    with rejected():
        GoodsReceiptLine.objects.create(
            receipt=receipt, line_no=1, item=item, quantity=D(1), unit_cost=D(0)
        )


# --- transfers -------------------------------------------------------------------------


def _dispatch(**overrides: object) -> Dispatch:
    user = make_user()
    data: dict[str, object] = {
        "origin": make_branch(kind="warehouse"),
        "destination": make_branch(),
        "status": "in_transit",
        "dispatched_by": user,
        "dispatched_at": timezone.now(),
        "operation": make_operation(actor=user, operation_type="dispatch"),
        **overrides,
    }
    return Dispatch.objects.create(**data)


def _line(dispatch: Dispatch, **values: object) -> DispatchLine:
    data: dict[str, object] = {"qty_dispatched": D("10"), **values}
    return DispatchLine.objects.create(dispatch=dispatch, line_no=1, item=make_item(), **data)


def test_dispatch_reference_is_generated_and_kind_defaults() -> None:
    dispatch = _dispatch()
    dispatch.refresh_from_db()
    assert dispatch.reference == f"DSP-{dispatch.pk:06d}"
    assert dispatch.kind == "warehouse_dispatch"


def test_dispatch_origin_and_destination_must_differ() -> None:
    branch = make_branch()
    with rejected():
        _dispatch(origin=branch, destination=branch)


@pytest.mark.parametrize("field", ["status", "kind"])
def test_dispatch_enumerations_are_enforced(field: str) -> None:
    with rejected():
        _dispatch(**{field: "nope"})


def test_dispatch_decision_needs_both_who_and_when() -> None:
    with rejected():
        _dispatch(decided_at=timezone.now())
    with rejected():
        _dispatch(decided_by=make_user())


@pytest.mark.parametrize(
    "values",
    [
        {"qty_dispatched": D("0")},
        {"qty_received": D("11"), "qty_accepted": D("11"), "qty_rejected": D("0")},  # overage (E3)
        {"qty_received": D("-1"), "qty_accepted": D("0"), "qty_rejected": D("-1")},
        {"qty_received": D("5"), "qty_accepted": D("6"), "qty_rejected": D("-1")},
        {"qty_received": D("5"), "qty_accepted": D("3"), "qty_rejected": D("1")},  # 5-3 != 1
        {"qty_received": D("5")},  # all three or none
        {"qty_received": D("5"), "qty_accepted": D("5")},
        {"qty_resolved": D("-1")},
        {"qty_resolved": D("11")},
        {
            "qty_received": D("8"),
            "qty_accepted": D("8"),
            "qty_rejected": D("0"),
            "qty_resolved": D("3"),
        },
        {"status": "lost"},
    ],
)
def test_dispatch_line_quantity_rules(values: dict[str, D]) -> None:
    with rejected():
        _line(_dispatch(), **values)


def test_dispatch_line_accepts_a_consistent_partial_receipt() -> None:
    line = _line(
        _dispatch(),
        qty_received=D("9"),
        qty_accepted=D("7"),
        qty_rejected=D("2"),
        qty_resolved=D("3"),
        status="under_investigation",
    )
    assert line.pk


def _discrepancy(short: str = "3", rejected_qty: str = "2") -> Discrepancy:
    user = make_user()
    line = _line(
        _dispatch(),
        qty_received=D("10") - D(short),
        qty_accepted=D("10") - D(short) - D(rejected_qty),
        qty_rejected=D(rejected_qty),
    )
    return Discrepancy.objects.create(
        dispatch_line=line,
        qty_short=D(short),
        qty_rejected=D(rejected_qty),
        note="n",
        flagged_by=user,
        flagged_at=timezone.now(),
        status="open",
    )


def test_discrepancy_needs_a_shortfall_or_rejection() -> None:
    with rejected():
        _discrepancy("0", "0")
    with rejected():
        _discrepancy("-1", "1")
    assert _discrepancy("0", "2").pk


def test_one_discrepancy_per_line() -> None:
    discrepancy = _discrepancy()
    with rejected():
        Discrepancy.objects.create(
            dispatch_line=discrepancy.dispatch_line,
            qty_short=D(1),
            qty_rejected=D(0),
            note="n",
            flagged_by=discrepancy.flagged_by,
            flagged_at=timezone.now(),
            status="open",
        )


def _resolve(
    discrepancy: Discrepancy, quantity: str, note: str = "returned", outcome: str = "return"
) -> None:
    user = make_user()
    DiscrepancyResolution.objects.create(
        discrepancy=discrepancy,
        outcome=outcome,
        quantity=D(quantity),
        note=note,
        resolved_by=user,
        role_used="warehouse_admin",
        resolved_at=timezone.now(),
        operation=make_operation(actor=user, operation_type="discrepancy_resolution"),
    )


def test_resolution_needs_a_note_a_known_outcome_and_a_positive_quantity() -> None:
    discrepancy = _discrepancy()
    for note in ("", "   "):
        with rejected():
            _resolve(discrepancy, "1", note=note)
    with rejected():
        _resolve(discrepancy, "1", outcome="gift")
    for quantity in ("0", "-1"):
        with rejected():
            _resolve(discrepancy, quantity)


def test_resolutions_may_be_split_but_never_exceed_the_flagged_quantity() -> None:
    discrepancy = _discrepancy("3", "2")  # 5 flagged
    _resolve(discrepancy, "3", outcome="return")
    _resolve(discrepancy, "1", outcome="loss")
    with rejected():
        _resolve(discrepancy, "2", outcome="damage")
    _resolve(discrepancy, "1", outcome="damage")


# --- sales -----------------------------------------------------------------------------


def _sale(**overrides: object) -> Sale:
    user = make_user()
    data: dict[str, object] = {
        "branch": make_branch(),
        "sold_by": user,
        "role_used": "front_staff",
        "payment_method": PaymentMethod.objects.get(code="cash"),
        "total": D("100.00"),
        "sold_at": timezone.now(),
        "operation": make_operation(actor=user, operation_type="sale"),
        **overrides,
    }
    return Sale.objects.create(**data)


def test_payment_methods_are_seeded() -> None:
    assert set(PaymentMethod.objects.values_list("code", flat=True)) == {
        "cash",
        "mobile_money",
        "card",
    }


def test_sale_reference_is_generated_and_status_defaults_to_completed() -> None:
    sale = _sale()
    sale.refresh_from_db()
    assert sale.reference == f"SAL-{sale.pk:06d}"
    assert sale.status == "completed"


def test_sale_total_is_not_negative_and_status_is_known() -> None:
    with rejected():
        _sale(total=D("-1"))
    with rejected():
        _sale(status="voided")


def test_cancelled_sale_needs_a_reason_and_a_time_and_only_then() -> None:
    now = timezone.now()
    user = make_user()
    cancel = {"status": "cancelled", "cancelled_by": user, "cancelled_at": now}
    with rejected():
        _sale(**cancel, cancel_reason=None)
    with rejected():
        _sale(**cancel, cancel_reason="   ")
    with rejected():
        _sale(status="cancelled", cancel_reason="why")  # no cancelled_at
    with rejected():
        _sale(cancelled_at=now)  # completed but cancelled_at set
    assert _sale(**cancel, cancel_reason="Customer changed mind").pk


@pytest.mark.parametrize(
    ("quantity", "unit_price", "line_total", "ok"),
    [
        ("2", "10.00", "20.00", True),
        ("1.500", "10.00", "15.00", True),
        ("0.250", "0.10", "0.03", True),  # 0.025 rounds half up
        ("0.125", "0.10", "0.01", True),  # 0.0125 rounds down
        ("2", "10.00", "19.99", False),
        ("0.250", "0.10", "0.02", False),
    ],
)
def test_sale_line_total_is_quantity_times_price_rounded_half_up(
    quantity: str, unit_price: str, line_total: str, ok: bool
) -> None:
    sale, item = _sale(), make_item()
    kwargs = {
        "sale": sale,
        "line_no": 1,
        "item": item,
        "quantity": D(quantity),
        "unit_price": D(unit_price),
        "line_total": D(line_total),
    }
    if ok:
        assert SaleLine.objects.create(**kwargs).pk
    else:
        with rejected():
            SaleLine.objects.create(**kwargs)


@pytest.mark.parametrize("values", [{"quantity": D("0")}, {"unit_price": D("-1")}])
def test_sale_line_quantity_positive_and_price_not_negative(values: dict[str, D]) -> None:
    data = {"quantity": D("1"), "unit_price": D("5.00"), "line_total": D("5.00"), **values}
    with rejected():
        SaleLine.objects.create(sale=_sale(), line_no=1, item=make_item(), **data)


# --- stock ledger ----------------------------------------------------------------------


def _entry(**overrides: object) -> Entry:
    user = make_user()
    operation = make_operation(actor=user)
    data: dict[str, object] = {
        "operation": operation,
        "idempotency_key": operation.idempotency_key,
        "location": make_branch(),
        "item": make_item(),
        "bucket": "on_hand",
        "delta": D("5"),
        "balance_after": D("5"),
        "reason": "supplier_receipt",
        "source_type": "goods_receipt",
        "source_id": 1,
        "source_ref": "GRN-000001",
        "source_line_id": 1,
        "actor": user,
        "role_used": "warehouse_admin",
        **overrides,
    }
    return Entry.objects.create(**data)


@pytest.mark.parametrize(
    "values",
    [
        {"delta": D("0")},
        {"balance_after": D("-1")},
        {"bucket": "in_transit"},
        {"reason": "because"},
        {"source_type": "mystery"},
    ],
)
def test_ledger_entry_rules(values: dict[str, object]) -> None:
    with rejected():
        _entry(**values)


def test_ledger_entry_accepts_negative_delta_for_a_decrease() -> None:
    assert _entry(delta=D("-2"), balance_after=D("3")).pk


def test_ledger_entry_cannot_be_posted_twice() -> None:
    first = _entry()
    with rejected():
        Entry.objects.create(
            operation=first.operation,
            idempotency_key=first.idempotency_key,
            location=first.location,
            item=first.item,
            bucket=first.bucket,
            delta=first.delta,
            balance_after=first.balance_after,
            reason=first.reason,
            source_type=first.source_type,
            source_id=first.source_id,
            source_ref=first.source_ref,
            source_line_id=first.source_line_id,
            actor=first.actor,
            role_used=first.role_used,
        )


def test_a_ledger_entry_is_reversed_at_most_once() -> None:
    original = _entry(delta=D("-1"), balance_after=D("0"), reason="sale", source_type="sale")
    _entry(reverses=original, delta=D("1"), reason="sale_cancel", source_type="sale")
    with rejected():
        _entry(reverses=original, delta=D("1"), reason="sale_cancel", source_type="sale")


def test_operation_key_is_unique_per_actor_and_type() -> None:
    first = make_operation()
    make_operation(actor=first.actor, operation_type="sale", idempotency_key=first.idempotency_key)
    make_operation(idempotency_key=first.idempotency_key)  # another actor: fine
    with rejected():
        make_operation(actor=first.actor, idempotency_key=first.idempotency_key)
    with rejected():
        make_operation(operation_type="refund")


# --- item SKU immutability (database trigger) --------------------------------------------


def test_sku_can_change_until_a_transaction_uses_the_item() -> None:
    item = make_item(sku="SKU-OLD")
    Item.objects.filter(pk=item.pk).update(sku="SKU-NEW")
    item.refresh_from_db()
    assert item.sku == "SKU-NEW"


def test_sku_is_frozen_once_the_item_has_a_ledger_entry() -> None:
    entry = _entry()
    with rejected(DatabaseError):
        Item.objects.filter(pk=entry.item_id).update(sku="SKU-CHANGED")


def test_sku_is_frozen_once_the_item_is_on_a_receipt_line() -> None:
    item = make_item()
    GoodsReceiptLine.objects.create(
        receipt=_receipt(), line_no=1, item=item, quantity=D(1), unit_cost=D(1)
    )
    with rejected(DatabaseError):
        Item.objects.filter(pk=item.pk).update(sku="SKU-CHANGED")


def test_other_item_fields_stay_editable_after_use() -> None:
    entry = _entry()
    Item.objects.filter(pk=entry.item_id).update(name="Renamed")
    assert Item.objects.get(pk=entry.item_id).name == "Renamed"

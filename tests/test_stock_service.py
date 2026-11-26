"""B2.5 / B2.6: the stock service posts balances, ledger and audit together, or nothing."""

import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from typing import Any

import pytest
from django.db import connection

from audit.models import AuditEvent
from config.errors import ApiError
from inventory.models import Brand, Category, Condition, Item, StockBalance
from stock_ledger.models import Bucket, MovementType, SourceType, StockMovement
from stock_ledger.services import StockChange, post_stock_changes


@pytest.fixture
def item(db: None) -> Item:
    brand = Brand.objects.create(name="TestBrand")
    return Item.objects.create(
        sku="SKU-T1",
        name="Test Laptop",
        category=Category.objects.get(name="Laptop"),
        brand=brand,
        condition=Condition.NEW,
    )


def change(
    loc: Any, item: Item, delta: int, *, bucket: str = Bucket.ON_HAND, line: int = 1, src: int = 1
) -> StockChange:
    return StockChange(
        location=loc,
        item=item,
        bucket=bucket,
        delta=delta,
        movement_type=MovementType.OPENING_BALANCE if delta > 0 else MovementType.SALE,
        source_type=SourceType.CSV_IMPORT if delta > 0 else SourceType.SALE,
        source_id=src,
        source_line_id=line,
    )


def balance(loc: Any, item: Item) -> StockBalance:
    return StockBalance.objects.get(location=loc, item=item)


def test_post_writes_balance_ledger_and_audit_together(locations: dict[str, Any], item: Item) -> None:
    op = uuid.uuid4()
    rows = post_stock_changes(
        [change(locations["a"], item, 5)], actor=None, actor_role="super_admin", operation_id=op
    )
    assert balance(locations["a"], item).on_hand == 5
    assert [(r.quantity_delta, r.balance_after, r.operation_id) for r in rows] == [(5, 5, op)]
    assert StockMovement.objects.filter(operation_id=op).count() == 1
    event = AuditEvent.objects.get(operation_id=op)
    assert event.action == "stock_posted" and (event.after_values or {})["rows"] == 1


def test_reserved_may_not_exceed_on_hand(locations: dict[str, Any], item: Item) -> None:
    a = locations["a"]
    post_stock_changes([change(a, item, 5)], actor=None)
    post_stock_changes([change(a, item, 2, bucket=Bucket.RESERVED, line=2)], actor=None)
    assert (balance(a, item).on_hand, balance(a, item).reserved) == (5, 2)
    with pytest.raises(ApiError) as exc:
        post_stock_changes([change(a, item, 4, bucket=Bucket.RESERVED, line=3)], actor=None)
    assert exc.value.status == 409
    assert balance(a, item).reserved == 2


def test_negative_stock_refused_and_nothing_written(locations: dict[str, Any], item: Item) -> None:
    a = locations["a"]
    post_stock_changes([change(a, item, 1)], actor=None)
    ledger, audit = StockMovement.objects.count(), AuditEvent.objects.count()
    with pytest.raises(ApiError) as exc:
        post_stock_changes([change(a, item, -2, line=2, src=2)], actor=None)
    assert exc.value.status == 409
    assert balance(a, item).on_hand == 1
    assert (StockMovement.objects.count(), AuditEvent.objects.count()) == (ledger, audit)


def test_a_multi_row_post_is_all_or_nothing(locations: dict[str, Any], item: Item) -> None:
    a, b = locations["a"], locations["b"]
    with pytest.raises(ApiError):
        post_stock_changes([change(a, item, 5), change(b, item, -1, line=2)], actor=None)
    assert not StockBalance.objects.filter(location=a, on_hand__gt=0).exists()
    assert StockMovement.objects.count() == 0


def test_same_source_line_cannot_post_twice(locations: dict[str, Any], item: Item) -> None:
    a = locations["a"]
    post_stock_changes([change(a, item, 5)], actor=None)
    with pytest.raises(ApiError) as exc:
        post_stock_changes([change(a, item, 5)], actor=None)
    assert (exc.value.status, exc.value.code) == (409, "conflict")
    assert balance(a, item).on_hand == 5
    assert StockMovement.objects.count() == 1


def test_duplicate_line_inside_one_post_is_409_and_writes_nothing(
    locations: dict[str, Any], item: Item
) -> None:
    a = locations["a"]
    with pytest.raises(ApiError) as exc:
        post_stock_changes([change(a, item, 5), change(a, item, 3)], actor=None)
    assert exc.value.status == 409
    assert StockMovement.objects.count() == 0 and not StockBalance.objects.filter(on_hand__gt=0).exists()


def test_every_running_balance_step_is_checked_not_only_the_final_one(
    locations: dict[str, Any], item: Item
) -> None:
    a = locations["a"]
    steps = [change(a, item, 1, line=1), change(a, item, -2, line=2), change(a, item, 5, line=3)]
    with pytest.raises(ApiError) as exc:  # 0 -> 1 -> -1 -> 4: the middle step goes negative
        post_stock_changes(steps, actor=None)
    assert (exc.value.status, exc.value.code) == (409, "insufficient_stock")
    assert StockMovement.objects.count() == 0


@pytest.mark.parametrize("bad", [0, None])
def test_bad_input_is_a_validation_error(locations: dict[str, Any], item: Item, bad: int | None) -> None:
    changes = [] if bad is None else [change(locations["a"], item, bad)]
    with pytest.raises(ApiError) as exc:
        post_stock_changes(changes, actor=None)
    assert exc.value.status == 400


def test_unknown_bucket_refused(locations: dict[str, Any], item: Item) -> None:
    with pytest.raises(ApiError):
        post_stock_changes([change(locations["a"], item, 1, bucket="nope")], actor=None)


@pytest.mark.django_db(transaction=True)
def test_two_sales_of_the_last_unit_exactly_one_wins(locations: dict[str, Any], item: Item) -> None:
    a = locations["a"]
    post_stock_changes([change(a, item, 1)], actor=None)
    barrier = Barrier(2)

    def sell(line: int) -> str:
        try:
            barrier.wait()
            post_stock_changes([change(a, item, -1, line=line, src=line)], actor=None)
            return "ok"
        except ApiError:
            return "refused"
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = sorted(pool.map(sell, [10, 11]))
    assert results == ["ok", "refused"]
    assert balance(a, item).on_hand == 0
    assert StockMovement.objects.filter(movement_type=MovementType.SALE).count() == 1


# ---- B4.3: operation-level idempotency, FIX-9 ----


def test_replaying_an_operation_returns_the_stored_rows_and_writes_nothing_more(
    locations: dict[str, Any], item: Item
) -> None:
    a, op = locations["a"], uuid.uuid4()
    first = post_stock_changes([change(a, item, 5)], actor=None, operation_id=op)
    again = post_stock_changes([change(a, item, 5)], actor=None, operation_id=op)
    assert [r.pk for r in again] == [r.pk for r in first]
    assert balance(a, item).on_hand == 5 and StockMovement.objects.count() == 1
    assert AuditEvent.objects.filter(operation_id=op).count() == 1


def test_the_same_operation_id_with_other_changes_is_409_idempotency_conflict(
    locations: dict[str, Any], item: Item
) -> None:
    a, op = locations["a"], uuid.uuid4()
    post_stock_changes([change(a, item, 5)], actor=None, operation_id=op)
    with pytest.raises(ApiError) as caught:
        post_stock_changes([change(a, item, 6)], actor=None, operation_id=op)
    assert caught.value.status == 409 and caught.value.code == "idempotency_conflict"
    assert balance(a, item).on_hand == 5


def test_the_same_csv_import_row_posted_twice_writes_one_ledger_row(
    locations: dict[str, Any], item: Item
) -> None:
    a = locations["a"]
    post_stock_changes([change(a, item, 4, src=7, line=3)], actor=None)
    with pytest.raises(ApiError) as caught:  # a fresh operation id, the same batch row
        post_stock_changes([change(a, item, 4, src=7, line=3)], actor=None)
    assert caught.value.status == 409 and caught.value.code == "conflict"
    rows = StockMovement.objects.filter(source_type=SourceType.CSV_IMPORT, source_id=7, source_line_id=3)
    assert rows.count() == 1 and balance(a, item).on_hand == 4


@pytest.mark.django_db(transaction=True)
def test_two_concurrent_copies_of_one_operation_post_once(locations: dict[str, Any], item: Item) -> None:
    a, op = locations["a"], uuid.uuid4()
    barrier = Barrier(2)

    def post(_: int) -> int:
        try:
            barrier.wait()
            return len(post_stock_changes([change(a, item, 5)], actor=None, operation_id=op))
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(post, [1, 2])) == [1, 1]  # both get the same single row back
    assert balance(a, item).on_hand == 5 and StockMovement.objects.count() == 1


@pytest.mark.django_db(transaction=True)
def test_same_operation_id_on_different_items_posts_once(locations: dict[str, Any], item: Item) -> None:
    other = Item.objects.create(
        sku="SKU-T2", name="Other", category=item.category, brand=item.brand, condition=Condition.NEW
    )
    a, op = locations["a"], uuid.uuid4()
    barrier = Barrier(2)

    def post(chosen: Item) -> str:
        try:
            barrier.wait()
            post_stock_changes([change(a, chosen, 5)], actor=None, operation_id=op)
            return "ok"
        except ApiError as exc:
            return exc.code
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = sorted(pool.map(post, [item, other]))
    assert results == ["idempotency_conflict", "ok"]
    assert StockMovement.objects.filter(operation_id=op).count() == 1

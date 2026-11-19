"""B2.1: the ledger and the audit log are append-only at every layer (ERD s7).

Layer 1 (model), layer 2 (queryset) and layer 3 (database triggers, for every role). Layer 4
(REVOKE of privileges) waits for the hosting decision (ERD E15).
"""

import pytest
from django.db import DatabaseError, connection, transaction

from audit.models import AuditEvent
from eqp4l.append_only import AppendOnlyError
from stock_ledger.models import Entry, Operation
from tests.factories import make_branch, make_item, make_operation, make_user

pytestmark = pytest.mark.django_db


def _entry() -> Entry:
    user = make_user()
    operation = make_operation(actor=user)
    return Entry.objects.create(
        operation=operation,
        idempotency_key=operation.idempotency_key,
        location=make_branch(),
        item=make_item(),
        bucket="on_hand",
        delta=1,
        balance_after=1,
        reason="supplier_receipt",
        source_type="goods_receipt",
        source_id=1,
        source_ref="GRN-000001",
        source_line_id=1,
        actor=user,
        role_used="warehouse_admin",
    )


def _event() -> AuditEvent:
    return AuditEvent.objects.create(action="auth.login", actor=make_user())


@pytest.fixture(params=["entry", "operation", "event"])
def row(request: pytest.FixtureRequest) -> Entry | Operation | AuditEvent:
    if request.param == "entry":
        return _entry()
    if request.param == "operation":
        return make_operation()
    return _event()


# --- layers 1 and 2: model and queryset ----------------------------------------------------


def test_saving_an_existing_row_raises(row: Entry | Operation | AuditEvent) -> None:
    with pytest.raises(AppendOnlyError):
        row.save()


def test_saving_a_row_after_it_was_just_created_raises_too(
    row: Entry | Operation | AuditEvent,
) -> None:
    fresh = type(row).objects.get(pk=row.pk)
    with pytest.raises(AppendOnlyError):
        fresh.save(force_update=True)


def test_deleting_a_row_raises(row: Entry | Operation | AuditEvent) -> None:
    with pytest.raises(AppendOnlyError):
        row.delete()


def test_queryset_update_delete_and_bulk_update_raise(row: Entry | Operation | AuditEvent) -> None:
    manager = type(row).objects
    with pytest.raises(AppendOnlyError):
        manager.all().update(pk=row.pk)
    with pytest.raises(AppendOnlyError):
        manager.all().delete()
    with pytest.raises(AppendOnlyError):
        manager.bulk_update([row], ["pk"])


def test_bulk_create_may_insert_but_never_upsert() -> None:
    event = AuditEvent(action="x.y")
    AuditEvent.objects.bulk_create([event])
    with pytest.raises(AppendOnlyError):
        AuditEvent.objects.bulk_create(
            [AuditEvent(pk=event.pk, action="changed")],
            update_conflicts=True,
            update_fields=["action"],
            unique_fields=["id"],
        )
    assert AuditEvent.objects.get(pk=event.pk).action == "x.y"


def test_get_or_create_and_update_or_create_cannot_change_a_row() -> None:
    event = _event()
    with pytest.raises(AppendOnlyError):
        AuditEvent.objects.update_or_create(pk=event.pk, defaults={"action": "changed"})


# --- layer 3: database triggers (raw SQL, as the table owner) -------------------------------

TABLES = ["stock_ledger_entry", "stock_ledger_operation", "audit_auditevent"]


def _make_row(table: str) -> None:
    if table == "stock_ledger_entry":
        _entry()
    elif table == "stock_ledger_operation":
        make_operation()
    else:
        _event()


@pytest.mark.parametrize("table", TABLES)
def test_raw_sql_update_is_rejected_by_the_database(table: str) -> None:
    _make_row(table)
    column = "actor_login_id" if table == "audit_auditevent" else "idempotency_key"
    value = "'x'" if table == "audit_auditevent" else f"{column}"
    with (
        pytest.raises(DatabaseError, match="append-only"),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute(f"UPDATE {table} SET {column} = {value}")  # noqa: S608  # nosec B608


@pytest.mark.parametrize("table", TABLES)
def test_raw_sql_delete_is_rejected_by_the_database(table: str) -> None:
    _make_row(table)
    with (
        pytest.raises(DatabaseError, match="append-only"),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute(f"DELETE FROM {table}")  # noqa: S608  # nosec B608


@pytest.mark.parametrize("table", TABLES)
def test_raw_sql_truncate_is_rejected_by_the_database(table: str) -> None:
    _make_row(table)
    # Fire the deferred foreign-key checks first: PostgreSQL refuses TRUNCATE while they are
    # pending, which would hide the guard trigger under test.
    with connection.cursor() as cursor:
        cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
    with (
        pytest.raises(DatabaseError, match="append-only"),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute(f"TRUNCATE TABLE {table} CASCADE")

    with connection.cursor() as cursor:
        cursor.execute(f"SELECT count(*) FROM {table}")  # noqa: S608  # nosec B608
        count = cursor.fetchone()
    assert count is not None
    assert count[0] >= 1


@pytest.mark.parametrize("table", TABLES)
def test_the_guard_triggers_exist(table: str) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT tgname FROM pg_trigger WHERE tgrelid = %s::regclass AND NOT tgisinternal",
            [table],
        )
        names = {r[0] for r in cursor.fetchall()}
    assert {f"{table}_no_change", f"{table}_no_truncate"} <= names


def test_inserting_is_still_allowed() -> None:
    assert _entry().pk
    assert _event().pk

# ruff: noqa: S608  (test-only SQL built from the fixed table list)
"""B2.1: append-only at the model layer, the database trigger layer and the role-grant layer."""

import uuid
from typing import Any

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import DatabaseError, connection, transaction

from audit.management.commands.lock_append_only_tables import APPEND_ONLY_TABLES
from audit.models import AuditEvent
from audit.services import record_event
from config.append_only import AppendOnlyError

pytestmark = pytest.mark.django_db


@pytest.fixture
def event() -> AuditEvent:
    return record_event("test_event", operation_id=uuid.uuid4())


def test_model_layer_refuses_save_delete_update(event: AuditEvent) -> None:
    event.action = "changed"
    with pytest.raises(AppendOnlyError):
        event.save()
    with pytest.raises(AppendOnlyError):
        event.delete()
    with pytest.raises(AppendOnlyError):
        AuditEvent.objects.filter(pk=event.pk).update(action="x")
    with pytest.raises(AppendOnlyError):
        AuditEvent.objects.filter(pk=event.pk).delete()
    with pytest.raises(AppendOnlyError):
        AuditEvent.objects.bulk_update([event], ["action"])
    assert AuditEvent.objects.get(pk=event.pk).action == "test_event"


_DEFAULTS = {
    "integer": "1",
    "bigint": "1",
    "smallint": "1",
    "numeric": "1",
    "boolean": "false",
    "uuid": "gen_random_uuid()",
    "timestamp with time zone": "now()",
    "date": "current_date",
    "jsonb": "'{}'",
    "inet": "'127.0.0.1'",
}


def _insert_dummy_row(cur: Any, table: str) -> None:
    """Insert one row of type defaults so the row triggers have something to refuse."""
    cur.execute(
        "SELECT conname FROM pg_constraint WHERE conrelid = %s::regclass AND contype IN ('c', 'f')", [table]
    )
    for (name,) in cur.fetchall():  # FKs and checks dropped here; DDL rolls back with the test transaction
        cur.execute(f'ALTER TABLE {table} DROP CONSTRAINT "{name}"')
    cur.execute(
        "SELECT column_name, data_type FROM information_schema.columns WHERE table_name = %s "
        "AND is_nullable = 'NO' AND column_default IS NULL AND is_identity = 'NO'",
        [table],
    )
    cols = cur.fetchall()
    values = [_DEFAULTS.get(t, "'x'") for _, t in cols]
    names = ", ".join(f'"{n}"' for n, _ in cols)
    cur.execute(f"INSERT INTO {table} ({names}) VALUES ({', '.join(values)})")


@pytest.mark.parametrize("table", APPEND_ONLY_TABLES)
@pytest.mark.parametrize("verb", ["UPDATE", "DELETE", "TRUNCATE"])
def test_database_trigger_refuses_raw_sql(table: str, verb: str) -> None:
    with connection.cursor() as cur:
        cur.execute("SET CONSTRAINTS ALL DEFERRED")
        _insert_dummy_row(cur, table)
        cur.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = %s LIMIT 1", [table]
        )
        col = cur.fetchone()[0]
        sql = {
            "UPDATE": f'UPDATE {table} SET "{col}" = "{col}"',
            "DELETE": f"DELETE FROM {table}",
            "TRUNCATE": f"TRUNCATE {table}",
        }[verb]
        with pytest.raises(DatabaseError), transaction.atomic():
            cur.execute(sql)


@pytest.mark.parametrize("table", APPEND_ONLY_TABLES)
def test_lock_command_grants_insert_select_only(table: str) -> None:
    with connection.cursor() as cur:
        cur.execute("CREATE ROLE test_app_runtime NOLOGIN")
    call_command("lock_append_only_tables", role="test_app_runtime")
    with connection.cursor() as cur:

        def has(priv: str) -> bool:
            cur.execute("SELECT has_table_privilege('test_app_runtime', %s, %s)", [table, priv])
            return bool(cur.fetchone()[0])

        assert has("INSERT") and has("SELECT")
        assert not has("UPDATE") and not has("DELETE") and not has("TRUNCATE")


@pytest.mark.parametrize("role", ["Bad-Role", "x; DROP TABLE a", "UPPER"])
def test_lock_command_rejects_bad_role_names(role: str) -> None:
    with pytest.raises(CommandError):
        call_command("lock_append_only_tables", role=role)

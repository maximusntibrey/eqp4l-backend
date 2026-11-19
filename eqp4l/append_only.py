"""Append-only guards for the stock ledger and the audit log (ERD s7).

Layers 1 and 2 (model and queryset) live here; layer 3 (database triggers that reject
UPDATE, DELETE and TRUNCATE for every role) is built by :func:`append_only_operations` and
used in the migrations of ``stock_ledger`` and ``audit``.
"""

from typing import Any, NoReturn

from django.db import migrations, models
from django.db.migrations.operations.base import Operation


class AppendOnlyError(Exception):
    """Raised when code tries to change or delete a row of an append-only table."""


def _refuse(action: str) -> NoReturn:
    raise AppendOnlyError(f"{action} is not allowed: this table is append-only.")


class AppendOnlyQuerySet(models.QuerySet[Any]):
    """Only ``create()`` and ``bulk_create()`` exist; every other write raises."""

    def update(self, **kwargs: Any) -> NoReturn:
        _refuse("update()")

    def delete(self) -> NoReturn:
        _refuse("delete()")

    def bulk_update(self, objs: Any, fields: Any, batch_size: Any = None) -> NoReturn:
        _refuse("bulk_update()")

    def bulk_create(self, objs: Any, *args: Any, **kwargs: Any) -> Any:
        if kwargs.get("update_conflicts"):
            _refuse("bulk_create(update_conflicts=True)")
        return super().bulk_create(objs, *args, **kwargs)


class AppendOnlyModel(models.Model):
    """An existing row can never be saved again or deleted (ERD s7 layer 1)."""

    objects = AppendOnlyQuerySet.as_manager()

    class Meta:
        abstract = True

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self._state.adding:
            _refuse("Changing an existing row")
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> NoReturn:
        _refuse("delete()")


FUNCTION_SQL = """
CREATE OR REPLACE FUNCTION eqp4l_reject_change() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION '% on % is not allowed: the table is append-only', TG_OP, TG_TABLE_NAME
        USING ERRCODE = 'restrict_violation';
END;
$$;
"""
DROP_FUNCTION_SQL = "DROP FUNCTION IF EXISTS eqp4l_reject_change();"


def append_only_operations(table: str) -> list[Operation]:
    """Migration operations adding the UPDATE/DELETE and TRUNCATE guard triggers (layer 3)."""
    return [
        migrations.RunSQL(
            sql=[
                f"CREATE TRIGGER {table}_no_change BEFORE UPDATE OR DELETE ON {table} "
                "FOR EACH ROW EXECUTE FUNCTION eqp4l_reject_change();",
                f"CREATE TRIGGER {table}_no_truncate BEFORE TRUNCATE ON {table} "
                "FOR EACH STATEMENT EXECUTE FUNCTION eqp4l_reject_change();",
            ],
            reverse_sql=[
                f"DROP TRIGGER {table}_no_truncate ON {table};",
                f"DROP TRIGGER {table}_no_change ON {table};",
            ],
        )
    ]

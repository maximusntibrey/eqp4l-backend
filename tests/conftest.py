"""Shared test setup.

The append-only tables carry ``BEFORE TRUNCATE`` triggers that reject TRUNCATE for every
role (ERD s7). Django's ``TransactionTestCase`` cleanup flushes with TRUNCATE, so for that
one operation the triggers are disabled and re-enabled inside the same transaction. The
guards themselves are tested in ``test_append_only.py`` with a plain TRUNCATE.
"""

from typing import Any

from django.db.backends.postgresql.operations import DatabaseOperations

GUARDED_TABLES = ["stock_ledger_operation", "stock_ledger_entry", "audit_auditevent"]
_original_sql_flush = DatabaseOperations.sql_flush


def _sql_flush_with_guards_paused(self: Any, *args: Any, **kwargs: Any) -> list[str]:
    statements: list[str] = _original_sql_flush(self, *args, **kwargs)
    pause = [f"ALTER TABLE {t} DISABLE TRIGGER {t}_no_truncate;" for t in GUARDED_TABLES]
    resume = [f"ALTER TABLE {t} ENABLE TRIGGER {t}_no_truncate;" for t in GUARDED_TABLES]
    return [*pause, *statements, *resume]


DatabaseOperations.sql_flush = _sql_flush_with_guards_paused  # type: ignore[method-assign]

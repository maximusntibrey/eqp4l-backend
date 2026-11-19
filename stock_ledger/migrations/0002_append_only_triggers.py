"""Database guard for the append-only ledger (ERD s7 layer 3).

``BEFORE UPDATE OR DELETE`` and ``BEFORE TRUNCATE`` triggers reject every change to
``stock_ledger_entry`` and ``stock_ledger_operation`` for every role, the owner included.
"""

from django.db import migrations

from eqp4l.append_only import (
    DROP_FUNCTION_SQL,
    FUNCTION_SQL,
    append_only_operations,
)


class Migration(migrations.Migration):
    dependencies = [("stock_ledger", "0001_initial")]
    operations = [
        migrations.RunSQL(FUNCTION_SQL, DROP_FUNCTION_SQL),
        *append_only_operations("stock_ledger_operation"),
        *append_only_operations("stock_ledger_entry"),
    ]

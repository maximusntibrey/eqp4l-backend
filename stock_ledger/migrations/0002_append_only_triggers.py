"""Database guard for the append-only ledger (ERD s7 layer 3).

``BEFORE UPDATE OR DELETE`` and ``BEFORE TRUNCATE`` triggers reject every change to
``stock_ledger_entry`` and ``stock_ledger_operation`` for every role, the owner included.
The SQL is written out here on purpose (no imports from project code).
"""

from django.db import migrations

FUNCTION_SQL = """
CREATE OR REPLACE FUNCTION eqp4l_reject_change() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION '% on % is not allowed: the table is append-only', TG_OP, TG_TABLE_NAME
        USING ERRCODE = 'restrict_violation';
END;
$$;
"""


class Migration(migrations.Migration):
    dependencies = [("stock_ledger", "0001_initial")]
    operations = [
        migrations.RunSQL(FUNCTION_SQL, "DROP FUNCTION IF EXISTS eqp4l_reject_change();"),
        migrations.RunSQL(
            sql=[
                "CREATE TRIGGER stock_ledger_operation_no_change BEFORE UPDATE OR DELETE ON stock_ledger_operation "
                "FOR EACH ROW EXECUTE FUNCTION eqp4l_reject_change();",
                "CREATE TRIGGER stock_ledger_operation_no_truncate BEFORE TRUNCATE ON stock_ledger_operation "
                "FOR EACH STATEMENT EXECUTE FUNCTION eqp4l_reject_change();",
            ],
            reverse_sql=[
                "DROP TRIGGER stock_ledger_operation_no_truncate ON stock_ledger_operation;",
                "DROP TRIGGER stock_ledger_operation_no_change ON stock_ledger_operation;",
            ],
        ),
        migrations.RunSQL(
            sql=[
                "CREATE TRIGGER stock_ledger_entry_no_change BEFORE UPDATE OR DELETE ON stock_ledger_entry "
                "FOR EACH ROW EXECUTE FUNCTION eqp4l_reject_change();",
                "CREATE TRIGGER stock_ledger_entry_no_truncate BEFORE TRUNCATE ON stock_ledger_entry "
                "FOR EACH STATEMENT EXECUTE FUNCTION eqp4l_reject_change();",
            ],
            reverse_sql=[
                "DROP TRIGGER stock_ledger_entry_no_truncate ON stock_ledger_entry;",
                "DROP TRIGGER stock_ledger_entry_no_change ON stock_ledger_entry;",
            ],
        ),
    ]

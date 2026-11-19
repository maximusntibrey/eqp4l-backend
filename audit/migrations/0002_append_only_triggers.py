"""Database guard for the append-only audit log (ERD s7 layer 3).

The trigger function ``eqp4l_reject_change`` is created in ``stock_ledger/0002``.
"""

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("audit", "0001_initial"),
        ("stock_ledger", "0002_append_only_triggers"),
    ]
    operations = [
        migrations.RunSQL(
            sql=[
                "CREATE TRIGGER audit_auditevent_no_change BEFORE UPDATE OR DELETE ON audit_auditevent "
                "FOR EACH ROW EXECUTE FUNCTION eqp4l_reject_change();",
                "CREATE TRIGGER audit_auditevent_no_truncate BEFORE TRUNCATE ON audit_auditevent "
                "FOR EACH STATEMENT EXECUTE FUNCTION eqp4l_reject_change();",
            ],
            reverse_sql=[
                "DROP TRIGGER audit_auditevent_no_truncate ON audit_auditevent;",
                "DROP TRIGGER audit_auditevent_no_change ON audit_auditevent;",
            ],
        ),
    ]

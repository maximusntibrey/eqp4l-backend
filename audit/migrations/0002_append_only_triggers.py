"""Database guard for the append-only audit log (ERD s7 layer 3)."""

from django.db import migrations

from eqp4l.append_only import append_only_operations


class Migration(migrations.Migration):
    dependencies = [
        ("audit", "0001_initial"),
        # The trigger function is created in stock_ledger 0002.
        ("stock_ledger", "0002_append_only_triggers"),
    ]
    operations = [*append_only_operations("audit_auditevent")]

"""ERD s4: the login ID counters cannot be wiped by TRUNCATE either (IDs are never reused)."""

from django.db import migrations

FORWARD = [
    """CREATE TRIGGER login_id_sequence_no_truncate BEFORE TRUNCATE ON accounts_loginidsequence
    FOR EACH STATEMENT EXECUTE FUNCTION forbid_modification();""",
]
BACKWARD = ["DROP TRIGGER login_id_sequence_no_truncate ON accounts_loginidsequence;"]


class Migration(migrations.Migration):
    dependencies = [("accounts", "0004_login_id_guards")]
    operations = [migrations.RunSQL(sql=FORWARD, reverse_sql=BACKWARD)]

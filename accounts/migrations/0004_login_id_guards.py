"""ERD s4: login IDs are immutable and the ID counters only ever increase (never reused)."""

from django.db import migrations

FORWARD = [
    """CREATE FUNCTION forbid_login_id_change() RETURNS trigger AS $$
BEGIN
    IF NEW.login_id IS DISTINCT FROM OLD.login_id THEN
        RAISE EXCEPTION 'users.login_id is immutable' USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;""",
    """CREATE TRIGGER users_login_id_immutable BEFORE UPDATE ON accounts_user
    FOR EACH ROW EXECUTE FUNCTION forbid_login_id_change();""",
    """CREATE FUNCTION guard_login_id_sequence() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' OR NEW.prefix IS DISTINCT FROM OLD.prefix OR NEW.last_number < OLD.last_number THEN
        RAISE EXCEPTION 'login ID counters only increase' USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;""",
    """CREATE TRIGGER login_id_sequence_guard BEFORE UPDATE OR DELETE ON accounts_loginidsequence
    FOR EACH ROW EXECUTE FUNCTION guard_login_id_sequence();""",
]
BACKWARD = [
    "DROP TRIGGER login_id_sequence_guard ON accounts_loginidsequence;",
    "DROP FUNCTION guard_login_id_sequence();",
    "DROP TRIGGER users_login_id_immutable ON accounts_user;",
    "DROP FUNCTION forbid_login_id_change();",
]


class Migration(migrations.Migration):
    dependencies = [("accounts", "0003_append_only_triggers")]
    operations = [migrations.RunSQL(sql=FORWARD, reverse_sql=BACKWARD)]

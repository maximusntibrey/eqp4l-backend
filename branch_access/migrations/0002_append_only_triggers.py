"""Layer 2 of the append-only rule (ERD s4): the database rejects UPDATE, DELETE and TRUNCATE."""

from django.db import migrations

FUNCTION = """CREATE OR REPLACE FUNCTION forbid_modification() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'table % is append-only: % is not allowed', TG_TABLE_NAME, TG_OP
        USING ERRCODE = 'integrity_constraint_violation';
END;
$$ LANGUAGE plpgsql;"""

TABLES = ['branch_access_switchlog']


def forward() -> list[str]:
    sql = [FUNCTION]
    for t in TABLES:
        sql.append(f"CREATE TRIGGER {t}_append_only_rows BEFORE UPDATE OR DELETE ON {t} FOR EACH ROW EXECUTE FUNCTION forbid_modification();")
        sql.append(f"CREATE TRIGGER {t}_append_only_truncate BEFORE TRUNCATE ON {t} FOR EACH STATEMENT EXECUTE FUNCTION forbid_modification();")
    return sql


def backward() -> list[str]:
    sql = []
    for t in TABLES:
        sql.append(f"DROP TRIGGER {t}_append_only_rows ON {t};")
        sql.append(f"DROP TRIGGER {t}_append_only_truncate ON {t};")
    return sql


class Migration(migrations.Migration):
    dependencies = [("branch_access", "0001_initial")]
    operations = [migrations.RunSQL(sql=forward(), reverse_sql=backward())]

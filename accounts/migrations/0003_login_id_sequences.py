"""Login ID generator and immutability (B2.2, ERD s3.1).

* Two sequences, ``accounts_sa_seq`` (``SA-0001``...) and ``accounts_usr_seq``
  (``USR-0001``...). Sequences are not transactional, so a number is never issued twice
  even if the creating transaction rolls back or the user is later deactivated or removed.
* A trigger rejects any UPDATE that changes ``accounts_user.login_id``.
"""

from django.db import migrations

FUNCTION = """
CREATE FUNCTION accounts_user_login_id_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'login_id of user % is immutable', OLD.id
        USING ERRCODE = 'restrict_violation';
END;
$$;
"""


class Migration(migrations.Migration):
    dependencies = [("accounts", "0002_initial")]
    operations = [
        migrations.RunSQL(
            [
                "CREATE SEQUENCE accounts_sa_seq AS bigint START WITH 1 INCREMENT BY 1 NO CYCLE;",
                "CREATE SEQUENCE accounts_usr_seq AS bigint START WITH 1 INCREMENT BY 1 NO CYCLE;",
            ],
            ["DROP SEQUENCE accounts_usr_seq;", "DROP SEQUENCE accounts_sa_seq;"],
        ),
        migrations.RunSQL(
            [
                FUNCTION,
                "CREATE TRIGGER accounts_user_login_id_immutable "
                "BEFORE UPDATE OF login_id ON accounts_user FOR EACH ROW "
                "WHEN (OLD.login_id IS DISTINCT FROM NEW.login_id) "
                "EXECUTE FUNCTION accounts_user_login_id_guard();",
            ],
            [
                "DROP TRIGGER accounts_user_login_id_immutable ON accounts_user;",
                "DROP FUNCTION accounts_user_login_id_guard();",
            ],
        ),
    ]

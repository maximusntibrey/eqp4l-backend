"""Login ID generator (B2.2, ERD s3.1).

Two PostgreSQL sequences created by the first accounts migration, ``accounts_sa_seq`` and
``accounts_usr_seq``. ``nextval`` is atomic across connections and is NOT rolled back with a
transaction, so two concurrent creations never receive the same number and a number burned by
a rolled-back creation (or by a deleted or deactivated user) is never issued again.
"""

from django.db import connection

SA_PREFIX = "SA"
USR_PREFIX = "USR"
SEQUENCES = {SA_PREFIX: "accounts_sa_seq", USR_PREFIX: "accounts_usr_seq"}


def next_login_id(*, super_admin: bool) -> str:
    """Return the next unused login ID: ``SA-0001`` for Super Admins, ``USR-0001`` for others.

    Rule: IDs are issued only from the sequences, zero-padded to 4 digits (5+ digits after
    9999), and never reused (ERD s3.1, E8). Writes no audit event; the caller that creates
    the user does (``user.created``).
    """
    prefix = SA_PREFIX if super_admin else USR_PREFIX
    with connection.cursor() as cursor:
        cursor.execute("SELECT nextval(%s)", [SEQUENCES[prefix]])
        row = cursor.fetchone()
    if row is None:  # pragma: no cover - nextval always returns a row
        raise RuntimeError("nextval returned no row")
    return f"{prefix}-{int(row[0]):04d}"

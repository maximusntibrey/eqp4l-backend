"""B2.2: the custom user model and the login ID generator (ERD s3.1).

IDs: ``SA-0001`` for Super Admins, ``USR-0001`` for everyone else; immutable; never reused.
The sequences are not transactional, so the tests that need known numbers move them with
``setval`` first and the concurrency test runs on real committed transactions.
"""

import threading
from collections.abc import Iterator
from typing import Any

import pytest
from django.contrib.auth import authenticate, get_user_model
from django.db import DatabaseError, connection, connections, transaction

from accounts.ids import next_login_id
from accounts.models import User, UserStatus
from tests.factories import make_user

PASSWORD = "a-Long-Pass-123"  # noqa: S105  # nosec B105 - test value
WRONG_PASSWORD = "wrong"  # noqa: S105  # nosec B105 - test value


def _restart(sa: int = 1, usr: int = 1) -> None:
    """Make the next issued numbers ``sa`` and ``usr`` (test set-up only)."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT setval('accounts_sa_seq', %s, false)", [sa])
        cursor.execute("SELECT setval('accounts_usr_seq', %s, false)", [usr])


def _create(*, super_admin: bool = False, **kw: Any) -> User:
    return User.objects.create_user(
        full_name="Test Person",
        phone="0240000000",
        password=PASSWORD,
        super_admin=super_admin,
        **kw,
    )


@pytest.fixture
def fresh_sequences() -> Iterator[None]:
    _restart()
    yield
    _restart()


def test_auth_user_model_is_the_custom_user() -> None:
    assert get_user_model() is User
    assert User.USERNAME_FIELD == "login_id"
    assert not hasattr(User, "user_permissions")  # no PermissionsMixin (ERD s3.1)


@pytest.mark.django_db
@pytest.mark.usefixtures("fresh_sequences")
def test_super_admins_get_sa_numbers_and_everyone_else_usr_numbers() -> None:
    assert [_create(super_admin=True).login_id, _create(super_admin=True).login_id] == [
        "SA-0001",
        "SA-0002",
    ]
    assert [_create().login_id, _create().login_id] == ["USR-0001", "USR-0002"]
    assert _create(super_admin=True).login_id == "SA-0003"  # the two sequences are independent


@pytest.mark.django_db
@pytest.mark.usefixtures("fresh_sequences")
def test_ids_are_padded_to_four_digits_and_grow_past_9999() -> None:
    _restart(sa=9999, usr=9)
    assert next_login_id(super_admin=True) == "SA-9999"
    assert next_login_id(super_admin=True) == "SA-10000"
    assert next_login_id(super_admin=False) == "USR-0009"
    assert next_login_id(super_admin=False) == "USR-0010"


@pytest.mark.django_db
def test_every_generated_id_matches_the_database_format_check() -> None:
    user = _create()
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT login_id ~ '^(SA|USR)-[0-9]{4,}$' FROM accounts_user WHERE id = %s", [user.pk]
        )
        row = cursor.fetchone()
    assert row == (True,)


@pytest.mark.django_db
def test_create_user_hashes_the_password_and_the_user_can_authenticate() -> None:
    user = _create()
    assert user.password.startswith("argon2$")
    assert authenticate(username=user.login_id, password=PASSWORD) == user
    assert authenticate(username=user.login_id, password=WRONG_PASSWORD) is None


@pytest.mark.django_db
@pytest.mark.parametrize(
    "status", [UserStatus.PENDING, UserStatus.SUSPENDED, UserStatus.DEACTIVATED]
)
def test_only_active_users_can_authenticate(status: UserStatus) -> None:
    user = _create(status=status)
    assert user.is_active is False
    assert authenticate(username=user.login_id, password=PASSWORD) is None


@pytest.mark.django_db
def test_a_user_without_a_login_id_cannot_be_saved() -> None:
    with pytest.raises(ValueError, match="login_id"):
        User(full_name="A", phone="1", status="active").save()


# --- immutable ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_login_id_cannot_be_changed_through_the_model() -> None:
    user = User.objects.get(pk=_create().pk)
    original = user.login_id
    user.login_id = "USR-9999"
    with pytest.raises(ValueError, match="immutable"):
        user.save()
    assert User.objects.get(pk=user.pk).login_id == original


@pytest.mark.django_db
def test_other_fields_can_still_be_edited_and_saved_repeatedly() -> None:
    user = _create()
    user.full_name = "New Name"
    user.save()
    user.phone = "0200000000"
    user.save()
    assert User.objects.get(pk=user.pk).full_name == "New Name"


def _change_login_id(user: User, how: str) -> None:
    if how == "queryset":
        User.objects.filter(pk=user.pk).update(login_id="USR-9998")
    else:
        with connection.cursor() as cursor:
            cursor.execute("UPDATE accounts_user SET login_id = 'SA-9998' WHERE id = %s", [user.pk])


@pytest.mark.django_db
@pytest.mark.parametrize("how", ["queryset", "sql"])
def test_login_id_cannot_be_changed_in_the_database(how: str) -> None:
    user = _create()
    with pytest.raises(DatabaseError, match="immutable"), transaction.atomic():
        _change_login_id(user, how)
    assert User.objects.get(pk=user.pk).login_id == user.login_id


@pytest.mark.django_db
def test_updating_other_columns_is_not_blocked_by_the_trigger() -> None:
    user = _create()
    assert User.objects.filter(pk=user.pk).update(full_name="Other") == 1


# --- never reused ------------------------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.usefixtures("fresh_sequences")
def test_a_deactivated_users_id_is_not_issued_again() -> None:
    first = _create()
    first.status = UserStatus.DEACTIVATED
    first.save()
    assert first.login_id == "USR-0001"
    assert _create().login_id == "USR-0002"


@pytest.mark.django_db
def test_the_model_refuses_to_delete_a_user() -> None:
    user = _create()
    with pytest.raises(ValueError, match="never deleted"):
        user.delete()
    assert User.objects.filter(pk=user.pk).exists()


@pytest.mark.django_db
@pytest.mark.usefixtures("fresh_sequences")
def test_an_id_is_not_reused_even_if_the_row_is_removed_in_the_database() -> None:
    first = _create()
    with connection.cursor() as cursor:  # a privileged clean-up outside the application
        cursor.execute("DELETE FROM accounts_user WHERE id = %s", [first.pk])
    assert not User.objects.filter(pk=first.pk).exists()
    assert _create().login_id == "USR-0002"


def _create_then_fail() -> None:
    assert _create().login_id == "USR-0001"
    raise RuntimeError("boom")


@pytest.mark.django_db(transaction=True)
@pytest.mark.usefixtures("fresh_sequences")
def test_a_rolled_back_creation_burns_its_number_and_does_not_give_it_out_again() -> None:
    with pytest.raises(RuntimeError, match="boom"), transaction.atomic():
        _create_then_fail()
    assert User.objects.count() == 0
    assert _create().login_id == "USR-0002"


@pytest.mark.django_db
def test_factory_built_users_do_not_need_the_generator() -> None:
    assert make_user(login_id="USR-8123").login_id == "USR-8123"


# --- concurrency (two threads, real PostgreSQL, committed transactions) --------------------


@pytest.mark.django_db(transaction=True)
@pytest.mark.usefixtures("fresh_sequences")
def test_concurrent_creation_never_issues_the_same_id_twice() -> None:
    """Two connections each hold an open transaction at the same moment while creating."""
    rounds = 8
    barrier = threading.Barrier(2)
    issued: list[list[str]] = [[], []]
    backends: set[int] = set()
    errors: list[BaseException] = []

    def worker(index: int) -> None:
        try:
            for _ in range(rounds):
                with transaction.atomic():
                    issued[index].append(_create().login_id)
                    with connection.cursor() as cursor:
                        cursor.execute("SELECT pg_backend_pid()")
                        row = cursor.fetchone()
                    assert row is not None
                    backends.add(row[0])
                    barrier.wait(timeout=10)  # both transactions are open here
        except BaseException as exc:
            errors.append(exc)
            barrier.abort()
        finally:
            connections.close_all()

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)

    assert not errors
    assert len(backends) == 2  # really two database connections
    everyone = issued[0] + issued[1]
    assert len(set(everyone)) == len(everyone) == 2 * rounds  # no duplicates
    assert set(everyone) == {f"USR-{n:04d}" for n in range(1, 2 * rounds + 1)}  # no gaps
    assert User.objects.count() == 2 * rounds


@pytest.mark.django_db(transaction=True)
@pytest.mark.usefixtures("fresh_sequences")
def test_concurrent_creation_of_both_kinds_keeps_the_two_sequences_apart() -> None:
    barrier = threading.Barrier(2)
    issued: dict[bool, list[str]] = {True: [], False: []}

    def worker(super_admin: bool) -> None:
        try:
            barrier.wait(timeout=10)
            for _ in range(10):
                issued[super_admin].append(_create(super_admin=super_admin).login_id)
        finally:
            connections.close_all()

    threads = [threading.Thread(target=worker, args=(kind,)) for kind in (True, False)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)

    assert issued[True] == [f"SA-{n:04d}" for n in range(1, 11)]
    assert issued[False] == [f"USR-{n:04d}" for n in range(1, 11)]

"""B2.2 / B2.6: SA-0001 and USR-0001 IDs: generated under a lock, immutable, never reused."""

import re
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from typing import Any

import pytest
from django.db import DatabaseError, connection, transaction

from accounts.models import LoginIdSequence, User, UserStatus
from accounts.services import create_user, next_login_id
from config.errors import ApiError
from roles.models import UserRole
from roles.services import role_codes

pytestmark = pytest.mark.django_db


def test_super_admins_get_sa_ids_and_everyone_else_usr_ids(locations: dict[str, Any]) -> None:
    sa1, _ = create_user(full_name="One", role_codes=["super_admin"])
    wa, _ = create_user(full_name="Two", role_codes=["warehouse_admin"], permanent_location=locations["wh"])
    ba, _ = create_user(full_name="Three", role_codes=["branch_admin"], permanent_location=locations["a"])
    fs, _ = create_user(full_name="Four", role_codes=["front_staff"])
    sa2, _ = create_user(full_name="Five", role_codes=["super_admin"])
    assert [u.login_id for u in (sa1, wa, ba, fs, sa2)] == [
        "SA-0001",
        "USR-0001",
        "USR-0002",
        "USR-0003",
        "SA-0002",
    ]
    assert all(re.fullmatch(r"(SA|USR)-\d{4,}", u.login_id) for u in (sa1, wa, ba, fs, sa2))


def test_a_deactivated_users_id_is_never_issued_again() -> None:
    first, _ = create_user(full_name="Leaver", role_codes=["front_staff"])
    User.objects.filter(pk=first.pk).update(status=UserStatus.DEACTIVATED)
    second, _ = create_user(full_name="Joiner", role_codes=["front_staff"])
    assert first.login_id == "USR-0001" and second.login_id == "USR-0002"
    assert User.objects.get(pk=first.pk).login_id == "USR-0001"  # deactivated users keep their ID


def test_a_failed_create_does_not_skip_or_reuse_an_id() -> None:
    with pytest.raises(ApiError):
        create_user(full_name="  ", role_codes=["front_staff"])
    with pytest.raises(ApiError):
        create_user(full_name="Bad role", role_codes=["nope"])
    assert create_user(full_name="Ok", role_codes=["front_staff"])[0].login_id == "USR-0001"


def test_login_id_cannot_be_changed_in_the_database() -> None:
    user, _ = create_user(full_name="Fixed", role_codes=["front_staff"])
    with pytest.raises(DatabaseError), transaction.atomic():
        User.objects.filter(pk=user.pk).update(login_id="USR-0099")
    user.full_name = "Renamed"  # other fields stay editable
    user.save()
    assert User.objects.get(pk=user.pk).login_id == "USR-0001"


def test_id_counters_only_increase() -> None:
    create_user(full_name="One", role_codes=["front_staff"])
    with pytest.raises(DatabaseError), transaction.atomic():
        LoginIdSequence.objects.filter(prefix="USR").update(last_number=0)
    with pytest.raises(DatabaseError), transaction.atomic():
        LoginIdSequence.objects.filter(prefix="USR").delete()
    assert LoginIdSequence.objects.get(prefix="USR").last_number == 1


def test_login_id_format_is_checked_by_the_database() -> None:
    with pytest.raises(DatabaseError), transaction.atomic():
        User.objects.create(login_id="BOB-1", full_name="Bad")


def test_new_user_has_a_one_time_password_and_is_pending() -> None:
    user, otp = create_user(full_name="New Person", role_codes=["front_staff"])
    assert len(otp) >= 10 and user.check_password(otp) and otp not in user.password
    assert user.status == UserStatus.PENDING_ACTIVATION and user.must_change_password
    assert user.one_time_password_issued_at is not None
    assert create_user(full_name="Other", role_codes=["front_staff"])[1] != otp


def test_location_rules(locations: dict[str, Any]) -> None:
    ok, _ = create_user(full_name="BA", role_codes=["branch_admin"], permanent_location=locations["a"])
    assert ok.permanent_location_id == locations["a"].pk
    for roles, loc in [
        (["branch_admin"], None),
        (["branch_admin"], locations["wh"]),
        (["warehouse_admin"], locations["a"]),
        (["warehouse_admin"], None),
        (["front_staff"], locations["a"]),
        (["super_admin"], locations["a"]),
        (["warehouse_admin", "branch_admin"], locations["a"]),
    ]:
        with pytest.raises(ApiError) as exc:
            create_user(full_name="X", role_codes=roles, permanent_location=loc, actor=None)
        assert exc.value.status == 400
    locations["b"].is_active = False
    locations["b"].save()
    with pytest.raises(ApiError):
        create_user(full_name="X", role_codes=["branch_admin"], permanent_location=locations["b"])


def test_only_a_super_admin_can_create_users_and_assign_several_roles(users: dict[str, Any]) -> None:
    for key in ("wa", "ba", "fs"):
        with pytest.raises(ApiError) as exc:
            create_user(full_name="X", role_codes=["front_staff"], actor=users[key])
        assert exc.value.status == 403
    # internal bootstrap (no actor) cannot assign several roles either
    with pytest.raises(ApiError) as exc:
        create_user(full_name="X", role_codes=["super_admin", "front_staff"])
    assert exc.value.status == 403
    user, _ = create_user(full_name="Both", role_codes=["super_admin", "front_staff"], actor=users["sa"])
    assert role_codes(user) == ["super_admin", "front_staff"] and user.login_id.startswith("SA-")
    assert UserRole.objects.filter(user=user, assigned_by=users["sa"]).count() == 2
    assert User.objects.get(pk=user.pk).created_by_id == users["sa"].pk


def test_next_login_id_is_four_digits_then_grows() -> None:
    LoginIdSequence.objects.filter(prefix="SA").update(last_number=9998)
    assert next_login_id("SA") == "SA-9999"
    assert next_login_id("SA") == "SA-10000"


@pytest.mark.django_db(transaction=True)
def test_concurrent_creates_get_distinct_ids() -> None:
    workers = 8
    barrier = Barrier(workers)

    def create(i: int) -> str:
        try:
            barrier.wait()
            return create_user(full_name=f"Racer {i}", role_codes=["front_staff"])[0].login_id
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=workers) as pool:
        ids = list(pool.map(create, range(workers)))
    assert len(set(ids)) == workers
    assert sorted(ids) == [f"USR-{n:04d}" for n in range(1, workers + 1)]
    assert LoginIdSequence.objects.get(prefix="USR").last_number == workers


@pytest.mark.django_db(transaction=True)
def test_concurrent_super_admin_and_user_creates_do_not_collide() -> None:
    barrier = Barrier(4)

    def create(args: tuple[int, str]) -> str:
        i, role = args
        try:
            barrier.wait()
            return create_user(full_name=f"R{i}", role_codes=[role])[0].login_id
        finally:
            connection.close()

    jobs = [(0, "super_admin"), (1, "super_admin"), (2, "front_staff"), (3, "front_staff")]
    with ThreadPoolExecutor(max_workers=4) as pool:
        ids = sorted(pool.map(create, jobs))
    assert ids == ["SA-0001", "SA-0002", "USR-0001", "USR-0002"]


def test_login_id_counter_table_cannot_be_truncated() -> None:
    with pytest.raises(DatabaseError), transaction.atomic(), connection.cursor() as cur:
        cur.execute("TRUNCATE accounts_loginidsequence")
    assert LoginIdSequence.objects.exists()

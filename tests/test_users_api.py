"""B3.3: user management API (table rows 4-9): create, edit, status, reset, per-person permissions."""

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from threading import Barrier
from typing import Any

import pytest
from django.contrib.sessions.models import Session
from django.db import connection
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import User, UserStatus
from audit.models import AuditEvent
from roles.models import UserPermission
from roles.services import role_codes
from stock_ledger.models import IdempotencyKey
from tests.api import call, client_as
from tests.conftest import PASSWORD, login

pytestmark = pytest.mark.django_db
URL = "/api/v1/users/"
USER_KEYS = {
    "id", "login_id", "full_name", "status", "roles", "permanent_location_id",
    "must_change_password", "permissions", "last_login_at", "created_at",
}  # fmt: skip


def create(client: APIClient, *, key: Any = None, **body: Any) -> Any:
    return call(client, "POST", URL, {"full_name": "New Person", "roles": ["front_staff"], **body}, key=key)


# ---- create -----------------------------------------------------------------------------------


def test_create_returns_the_one_time_password_once_and_stores_only_a_hash(
    users: dict[str, Any], locations: Any
) -> None:
    response = create(client_as(users["sa"]))
    body = response.json()
    assert response.status_code == 201 and set(body) == USER_KEYS | {
        "one_time_password",
        "one_time_password_expires_at",
    }
    assert body["login_id"].startswith("USR-") and body["status"] == "pending_activation"
    assert body["must_change_password"] is True and body["roles"] == ["front_staff"]
    assert len(body["one_time_password"]) == 12
    user = User.objects.get(pk=body["id"])
    assert user.check_password(body["one_time_password"]) and user.password != body["one_time_password"]
    assert abs(user.one_time_password_issued_at - timezone.now()) < timedelta(minutes=1)  # type: ignore[operator]
    expires = datetime.fromisoformat(body["one_time_password_expires_at"].replace("Z", "+00:00"))
    assert timedelta(hours=71) < expires - timezone.now() <= timedelta(hours=72)
    # never again: not in a read, not in the replay record, not in the audit trail
    assert "one_time_password" not in call(client_as(users["sa"]), "GET", f"{URL}{user.pk}/").json()
    assert body["one_time_password"] not in str(
        list(IdempotencyKey.objects.values_list("response_body", flat=True))
    )
    event = AuditEvent.objects.get(action="user_created")
    assert body["one_time_password"] not in str((event.before_values, event.after_values))
    assert (event.actor_id, event.target_ref) == (users["sa"].pk, user.login_id)
    assert event.after_values["roles"] == ["front_staff"]  # type: ignore[index]


def test_new_user_logs_in_with_the_password_and_must_change_it_first(
    users: dict[str, Any], locations: Any
) -> None:
    body = create(
        client_as(users["sa"]), roles=["branch_admin"], permanent_location_id=locations["a"].pk
    ).json()
    user = User.objects.get(pk=body["id"])
    client = APIClient()
    assert login(client, user, body["one_time_password"]).status_code == 200
    blocked = call(client, "GET", "/api/v1/dashboard/")
    assert blocked.status_code == 403 and blocked.json()["code"] == "password_change_required"
    changed = call(client, "POST", "/api/v1/auth/password/", {
        "current_password": body["one_time_password"], "new_password": "a-brand-new-password",
    }, key=False)  # fmt: skip
    assert changed.status_code == 204
    user.refresh_from_db()
    assert user.status == UserStatus.ACTIVE and not user.must_change_password
    assert call(client, "GET", "/api/v1/dashboard/").status_code == 200


def test_super_admin_account_gets_an_sa_id_and_several_roles_only_from_a_super_admin(
    users: dict[str, Any], locations: Any
) -> None:
    sa = client_as(users["sa"])
    assert create(sa, roles=["super_admin"]).json()["login_id"].startswith("SA-")
    both = create(sa, roles=["branch_admin", "front_staff"], permanent_location_id=locations["a"].pk).json()
    assert both["roles"] == ["branch_admin", "front_staff"]
    assert create(client_as(users["ba"]), roles=["branch_admin", "front_staff"]).status_code == 403


@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({"roles": ["branch_admin"]}, "permanent_location_id"),  # BA needs a branch
        ({"roles": ["branch_admin"], "permanent_location_id": "wh"}, "permanent_location_id"),
        ({"roles": ["warehouse_admin"], "permanent_location_id": "a"}, "permanent_location_id"),
        ({"roles": ["front_staff"], "permanent_location_id": "a"}, "permanent_location_id"),
        ({"roles": ["super_admin"], "permanent_location_id": "a"}, "permanent_location_id"),
        ({"roles": ["branch_admin"], "permanent_location_id": 99999}, "permanent_location_id"),
        ({"roles": ["warehouse_admin", "branch_admin"], "permanent_location_id": "a"}, "roles"),
        ({"roles": []}, "roles.0"),
        ({"roles": ["owner"]}, "roles.0"),
        ({"roles": "front_staff"}, "roles"),
        ({"full_name": "   "}, "full_name"),
        ({"full_name": "N" * 151}, "full_name"),
        ({"full_name": None}, "full_name"),
    ],
)
def test_create_rejects_bad_input_and_creates_nothing(
    body: dict[str, Any], field: str, users: dict[str, Any], locations: Any
) -> None:
    body = {
        k: locations[v].pk if k == "permanent_location_id" and isinstance(v, str) else v
        for k, v in body.items()
    }
    before = User.objects.count()
    response = create(client_as(users["sa"]), **body)
    data = response.json()
    assert response.status_code == 400 and data["code"] == "validation_error", data
    assert data["errors"][0]["field"].split(".")[0] == field.split(".")[0]
    assert User.objects.count() == before and not AuditEvent.objects.filter(action="user_created")


def test_empty_roles_list_is_a_400_on_the_roles_field(users: dict[str, Any]) -> None:
    response = call(client_as(users["sa"]), "POST", URL, {"full_name": "X", "roles": []})
    assert response.status_code == 400 and response.json()["errors"][0]["field"] == "roles"


def test_same_key_replays_the_same_user_and_password_without_a_second_account(
    users: dict[str, Any], locations: Any
) -> None:
    sa, key = client_as(users["sa"]), "0b8f4b3e-1d57-4c0a-8a35-5f2d3c4b5a69"
    first = create(sa, key=key)
    count = User.objects.count()
    again = create(sa, key=key)
    assert first.status_code == again.status_code == 201 and first.json() == again.json()
    assert User.objects.count() == count and AuditEvent.objects.filter(action="user_created").count() == 1
    clash = call(sa, "POST", URL, {"full_name": "Someone Else", "roles": ["front_staff"]}, key=key)
    assert clash.status_code == 409 and clash.json()["code"] == "idempotency_conflict"
    assert User.objects.count() == count


def test_replay_by_another_user_never_serves_the_first_users_response(users: dict[str, Any]) -> None:
    key = "5d41402a-bc4b-4a76-b9d1-9a8f2e0d7c11"
    first = create(client_as(users["sa"]), key=key).json()
    assert first["id"]
    assert create(client_as(users["ba"]), key=key).status_code == 403
    assert create(client_as(users["fs"]), key=key).status_code == 403


def test_missing_or_malformed_key_is_400_and_creates_nothing(users: dict[str, Any]) -> None:
    sa, before = client_as(users["sa"]), User.objects.count()
    for key in (False, "not-a-uuid", ""):
        response = create(sa, key=key)
        assert response.status_code == 400 and response.json()["errors"][0]["field"] == "Idempotency-Key"
    assert User.objects.count() == before


@pytest.mark.django_db(transaction=True)
def test_two_simultaneous_posts_with_one_key_create_one_user(users: dict[str, Any]) -> None:
    key, barrier = "7c9e6679-7425-40de-944b-e07fc1f90ae7", Barrier(2)
    clients = [client_as(users["sa"]) for _ in range(2)]
    before = User.objects.count()

    def post(client: APIClient) -> tuple[int, str]:
        try:
            barrier.wait()
            response = create(client, key=key)
            return response.status_code, response.json()["login_id"]
        finally:
            connection.close()

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(post, clients))
    assert results[0] == results[1] and results[0][0] == 201, results
    assert User.objects.count() == before + 1


# ---- list and read ----------------------------------------------------------------------------


def test_list_scope_per_role_and_wrong_branch_users_stay_hidden(
    users: dict[str, Any], make_user: Callable[..., Any]
) -> None:
    ba_b = make_user("branch_admin", "b")
    wa = call(client_as(users["wa"]), "GET", URL).json()
    assert [r["login_id"] for r in wa["results"]] == [users["wa"].login_id]  # warehouse only
    ba = call(client_as(users["ba"]), "GET", URL).json()
    assert [r["login_id"] for r in ba["results"]] == [users["ba"].login_id]  # own branch only
    sa = call(client_as(users["sa"]), "GET", URL).json()
    assert {r["login_id"] for r in sa["results"]} >= {u.login_id for u in (*users.values(), ba_b)}
    assert all(set(r) == USER_KEYS for r in sa["results"])
    forbidden = call(client_as(users["fs"]), "GET", URL)
    assert forbidden.status_code == 403 and forbidden.json()["code"] == "permission_denied"
    # reading one user outside the caller's scope is 404, not a leak
    assert call(client_as(users["ba"]), "GET", f"{URL}{ba_b.pk}/").status_code == 404
    assert call(client_as(users["wa"]), "GET", f"{URL}{users['ba'].pk}/").status_code == 404
    assert call(client_as(users["ba"]), "GET", f"{URL}{users['ba'].pk}/").status_code == 200
    assert call(client_as(users["sa"]), "GET", f"{URL}{ba_b.pk}/").status_code == 200


def test_list_filters_and_paging(users: dict[str, Any], make_user: Callable[..., Any]) -> None:
    make_user("front_staff", status=UserStatus.SUSPENDED)
    sa = client_as(users["sa"])
    assert {r["status"] for r in call(sa, "GET", URL, {"status": "suspended"}).json()["results"]} == {
        "suspended"
    }
    assert {r["roles"][0] for r in call(sa, "GET", URL, {"role": "front_staff"}).json()["results"]} == {
        "front_staff"
    }
    found = call(sa, "GET", URL, {"q": users["ba"].login_id.lower()}).json()
    assert [r["login_id"] for r in found["results"]] == [users["ba"].login_id]
    page = call(sa, "GET", URL, {"page_size": 2}).json()
    assert page["count"] == 6 and len(page["results"]) == 2 and page["next"] and page["page_size"] == 2
    assert call(sa, "GET", URL, {"status": "gone"}).status_code == 400
    assert call(sa, "GET", URL, {"role": "owner"}).status_code == 400
    assert call(sa, "GET", f"{URL}99999/").status_code == 404


# ---- edit -------------------------------------------------------------------------------------


def test_edit_name_role_and_location_keeps_the_login_id(users: dict[str, Any], locations: Any) -> None:
    sa = client_as(users["sa"])
    target = User.objects.get(pk=create(sa).json()["id"])
    login_id = target.login_id
    response = call(sa, "PATCH", f"{URL}{target.pk}/", {"full_name": " Ama Mensah "})
    assert response.status_code == 200 and response.json()["full_name"] == "Ama Mensah"
    response = call(
        sa,
        "PATCH",
        f"{URL}{target.pk}/",
        {"roles": ["branch_admin"], "permanent_location_id": locations["b"].pk},
    )
    body = response.json()
    assert response.status_code == 200 and body["roles"] == ["branch_admin"]
    assert body["permanent_location_id"] == locations["b"].pk and body["login_id"] == login_id
    response = call(
        sa, "PATCH", f"{URL}{target.pk}/", {"roles": ["front_staff"], "permanent_location_id": None}
    )
    assert response.status_code == 200 and response.json()["permanent_location_id"] is None
    assert role_codes(target) == ["front_staff"]  # the old role is gone, not added to
    event = AuditEvent.objects.filter(action="user_updated").latest("id")
    assert event.before_values["roles"] == ["branch_admin"] and event.after_values["roles"] == ["front_staff"]  # type: ignore[index]


@pytest.mark.parametrize(
    "body",
    [
        {"login_id": "USR-9999"},
        {"roles": ["branch_admin"]},  # needs a branch
        {"permanent_location_id": 1},  # FS has no location
        {"full_name": " "},
        {"roles": ["owner"]},
    ],
)
def test_edit_rejects_bad_input_and_changes_nothing(body: dict[str, Any], users: dict[str, Any]) -> None:
    target = users["fs"]
    response = call(client_as(users["sa"]), "PATCH", f"{URL}{target.pk}/", body)
    assert response.status_code == 400 and response.json()["code"] == "validation_error"
    target.refresh_from_db()
    assert target.full_name == "Test front_staff" and role_codes(target) == ["front_staff"]
    assert not AuditEvent.objects.filter(action="user_updated")


def test_edit_unknown_user_is_404(users: dict[str, Any]) -> None:
    assert call(client_as(users["sa"]), "PATCH", f"{URL}99999/", {"full_name": "X"}).status_code == 404


# ---- reset password ---------------------------------------------------------------------------


def test_reset_gives_a_new_one_time_password_ends_sessions_and_forces_a_change(users: dict[str, Any]) -> None:
    target, victim = users["ba"], APIClient()
    login(victim, target)
    assert victim.get("/api/v1/auth/me/").status_code == 200
    response = call(client_as(users["sa"]), "POST", f"{URL}{target.pk}/reset-password/")
    body = response.json()
    assert response.status_code == 200 and set(body) == {"one_time_password", "one_time_password_expires_at"}
    target.refresh_from_db()
    assert target.check_password(body["one_time_password"]) and not target.check_password(PASSWORD)
    assert target.must_change_password
    assert abs(target.one_time_password_issued_at - timezone.now()) < timedelta(minutes=1)
    assert victim.get("/api/v1/auth/me/").status_code == 401  # session ended at once
    assert login(APIClient(), target, PASSWORD).status_code == 401
    fresh = APIClient()
    assert login(fresh, target, body["one_time_password"]).status_code == 200
    assert fresh.get("/api/v1/auth/me/").json()["must_change_password"] is True
    event = AuditEvent.objects.get(action="password_reset")
    assert body["one_time_password"] not in str((event.before_values, event.after_values))


def test_reset_replay_shows_the_same_password_and_deactivated_accounts_are_refused(
    users: dict[str, Any], make_user: Callable[..., Any]
) -> None:
    sa, key = client_as(users["sa"]), "1c0e8d62-2d2b-4bb9-a1d3-7d0a8e6c9f10"
    url = f"{URL}{users['fs'].pk}/reset-password/"
    first, again = call(sa, "POST", url, key=key), call(sa, "POST", url, key=key)
    assert first.status_code == again.status_code == 200 and first.json() == again.json()
    assert AuditEvent.objects.filter(action="password_reset").count() == 1
    assert call(sa, "POST", url, key=key).json()["one_time_password"] not in str(
        list(IdempotencyKey.objects.values_list("response_body", flat=True))
    )
    gone = make_user("front_staff", status=UserStatus.DEACTIVATED)
    response = call(sa, "POST", f"{URL}{gone.pk}/reset-password/")
    assert response.status_code == 409 and response.json()["code"] == "invalid_status_transition"
    assert call(sa, "POST", f"{URL}99999/reset-password/").status_code == 404


# ---- status -----------------------------------------------------------------------------------


def set_status(client: APIClient, user: User, status: str, **extra: Any) -> Any:
    return call(client, "POST", f"{URL}{user.pk}/status/", {"status": status, **extra})


def test_suspend_ends_sessions_blocks_login_and_activate_restores(users: dict[str, Any]) -> None:
    target, victim, sa = users["fs"], APIClient(), client_as(users["sa"])
    login(victim, target)
    response = set_status(sa, target, "suspended", reason="Investigation")
    assert response.status_code == 200 and response.json()["status"] == "suspended"
    assert victim.get("/api/v1/auth/me/").status_code == 401
    assert Session.objects.count() == 1  # only the Super Admin's session is left
    refused = login(APIClient(), target)
    assert refused.status_code == 403 and refused.json()["code"] == "account_inactive"
    assert set_status(sa, target, "active").json()["status"] == "active"
    assert login(APIClient(), target).status_code == 200
    events = list(AuditEvent.objects.filter(action="user_status_changed").order_by("id"))
    assert events[0].before_values == {"status": "active"}
    assert events[0].after_values == {"status": "suspended", "reason": "Investigation", "sessions_ended": 1}


def test_deactivate_is_final_keeps_history_and_ends_sessions(users: dict[str, Any]) -> None:
    target, victim, sa = users["ba"], APIClient(), client_as(users["sa"])
    login(victim, target)
    assert set_status(sa, target, "deactivated").json()["status"] == "deactivated"
    assert victim.get("/api/v1/auth/me/").status_code == 401
    assert User.objects.filter(pk=target.pk).exists()  # history kept
    refused = set_status(sa, target, "active")
    assert refused.status_code == 409 and refused.json()["code"] == "invalid_status_transition"
    assert call(sa, "GET", f"{URL}{target.pk}/").json()["status"] == "deactivated"


def test_status_rules_self_same_pending_and_bad_input(
    users: dict[str, Any], make_user: Callable[..., Any]
) -> None:
    sa = client_as(users["sa"])
    own = set_status(sa, users["sa"], "suspended")
    assert own.status_code == 409 and own.json()["code"] == "conflict"
    assert set_status(sa, users["fs"], "active").status_code == 409  # already active
    pending = make_user("front_staff", status=UserStatus.PENDING_ACTIVATION, must_change_password=True)
    assert set_status(sa, pending, "active").status_code == 409  # pending leaves only by password change
    assert set_status(sa, pending, "suspended").status_code == 200
    # back from suspended an account that never changed its password is still pending (OQ-22)
    assert set_status(sa, pending, "active").json()["status"] == "pending_activation"
    for bad in ("pending_activation", "gone", None):
        response = set_status(sa, users["fs"], bad)  # type: ignore[arg-type]
        assert response.status_code == 400 and response.json()["errors"][0]["field"] == "status"
    assert call(sa, "POST", f"{URL}99999/status/", {"status": "suspended"}).status_code == 404
    long = set_status(sa, users["fs"], "suspended", reason="r" * 501)
    assert long.status_code == 400 and long.json()["errors"][0]["field"] == "reason"
    users["sa"].refresh_from_db()
    assert users["sa"].status == UserStatus.ACTIVE


def test_last_super_admin_cannot_lose_role_be_suspended_or_deactivated(
    users: dict[str, Any], make_user: Callable[..., Any]
) -> None:
    sa, loc = client_as(users["sa"]), users["ba"].permanent_location_id

    def demote(client: APIClient, user: User) -> Any:
        body = {"roles": ["branch_admin"], "permanent_location_id": loc}
        return call(client, "PATCH", f"{URL}{user.pk}/", body)

    for target in ("suspended", "deactivated"):
        refused = set_status(sa, users["sa"], target)
        assert refused.status_code == 409 and refused.json()["code"] == "conflict"
        assert "Super Admin" in refused.json()["message"]
    refused = demote(sa, users["sa"])
    assert refused.status_code == 409 and refused.json()["code"] == "conflict"
    assert role_codes(users["sa"]) == ["super_admin"]
    # a second active SA: the first can lose the role; the second is then the last
    second = make_user("super_admin")
    assert set_status(sa, second, "suspended").status_code == 200
    assert set_status(sa, second, "active").status_code == 200
    assert set_status(sa, second, "deactivated").status_code == 200
    third = make_user("super_admin")
    assert demote(client_as(third), users["sa"]).status_code == 200
    last = demote(client_as(third), third)
    assert last.status_code == 409 and role_codes(third) == ["super_admin"]


def test_branch_admin_sees_own_branch_users_and_front_staff_working_there(
    users: dict[str, Any], make_user: Callable[..., Any], locations: Any
) -> None:
    fs_a, fs_b = make_user("front_staff"), make_user("front_staff")
    ba_b = make_user("branch_admin", "b")
    fs_a_client = client_as(fs_a)  # one session, so a later switch replaces the branch
    call(fs_a_client, "PUT", "/api/v1/working-branch/", {"branch_id": locations["a"].pk})
    call(client_as(fs_b), "PUT", "/api/v1/working-branch/", {"branch_id": locations["b"].pk})
    ba = client_as(users["ba"])
    ids = {r["login_id"] for r in call(ba, "GET", URL).json()["results"]}
    assert ids == {users["ba"].login_id, fs_a.login_id}
    assert call(ba, "GET", f"{URL}{fs_a.pk}/").status_code == 200
    for hidden in (fs_b, ba_b, users["fs"]):  # other branch, other branch admin, FS with no branch
        assert call(ba, "GET", f"{URL}{hidden.pk}/").status_code == 404
    # FS switches away: no longer visible to branch A
    call(fs_a_client, "PUT", "/api/v1/working-branch/", {"branch_id": locations["b"].pk})
    assert call(ba, "GET", f"{URL}{fs_a.pk}/").status_code == 404


# ---- per-person permissions ---------------------------------------------------------------------


def test_grant_and_revoke_per_person_permissions_with_audit(users: dict[str, Any]) -> None:
    sa, fs = client_as(users["sa"]), client_as(users["fs"])
    url = f"{URL}{users['fs'].pk}/permissions/"
    assert call(sa, "GET", url).json() == {"permissions": []}
    assert "dispatches.receive" not in fs.get("/api/v1/auth/me/").json()["permissions"]
    response = call(sa, "PUT", url, {"permissions": ["receive_stock", "manage_prices", "discount"]})
    assert response.status_code == 200
    assert response.json() == {"permissions": ["receive_stock", "manage_prices", "discount"]}
    me = fs.get("/api/v1/auth/me/").json()
    assert {"dispatches.receive", "prices.manage"} <= set(me["permissions"])  # effective at once
    assert me["user"]["permissions"] == ["receive_stock", "manage_prices", "discount"]
    assert call(sa, "PUT", url, {"permissions": ["manage_prices"]}).json() == {
        "permissions": ["manage_prices"]
    }
    me = fs.get("/api/v1/auth/me/").json()
    assert "dispatches.receive" not in me["permissions"] and "prices.manage" in me["permissions"]
    actions = list(AuditEvent.objects.filter(action__startswith="permission_").order_by("id"))
    assert [(e.action, (e.after_values or e.before_values)["permission"]) for e in actions] == [  # type: ignore[index]
        ("permission_granted", "discount"),
        ("permission_granted", "manage_prices"),
        ("permission_granted", "receive_stock"),
        ("permission_revoked", "discount"),
        ("permission_revoked", "receive_stock"),
    ]
    assert all(e.actor_id == users["sa"].pk and e.target_ref == users["fs"].login_id for e in actions)
    assert UserPermission.objects.filter(user=users["fs"]).count() == 3  # revoked rows are kept
    assert (
        call(sa, "PUT", url, {"permissions": ["manage_prices"]}).status_code == 200
    )  # no change, no new audit
    assert AuditEvent.objects.filter(action__startswith="permission_").count() == 5
    assert call(sa, "PUT", url, {"permissions": []}).json() == {"permissions": []}
    assert call(sa, "PUT", url, {"permissions": ["manage_prices"]}).json() == {
        "permissions": ["manage_prices"]
    }


def test_a_grant_never_widens_branch_scope(users: dict[str, Any], locations: Any) -> None:
    fs = client_as(users["fs"])
    call(
        client_as(users["sa"]),
        "PUT",
        f"{URL}{users['fs'].pk}/permissions/",
        {"permissions": ["receive_stock"]},
    )
    assert fs.get("/api/v1/auth/me/").json()["working_branch"] is None
    assert (
        call(fs, "GET", URL).status_code == 403 and call(fs, "GET", "/api/v1/dashboard/").status_code == 403
    )


@pytest.mark.parametrize("bad", [["receive_stock"], ["nope"], "manage_prices", None])
def test_permissions_bad_input(bad: Any, users: dict[str, Any]) -> None:
    response = call(
        client_as(users["sa"]), "PUT", f"{URL}{users['ba'].pk}/permissions/", {"permissions": bad}
    )
    assert response.status_code == 400 and response.json()["errors"][0]["field"].startswith("permissions")
    assert not UserPermission.objects.exists()  # receive_stock is for Front Staff only (table s3)


def test_manage_prices_and_discount_may_be_held_by_any_role_and_unknown_user_is_404(
    users: dict[str, Any],
) -> None:
    sa = client_as(users["sa"])
    for key in ("wa", "ba", "fs"):
        url = f"{URL}{users[key].pk}/permissions/"
        assert call(sa, "PUT", url, {"permissions": ["manage_prices", "discount"]}).status_code == 200
    assert call(sa, "PUT", f"{URL}99999/permissions/", {"permissions": []}).status_code == 404
    assert call(sa, "GET", f"{URL}99999/permissions/").status_code == 404


def test_super_admin_lists_all_branches_by_default_and_filters_users_by_branch(
    users: dict[str, Any], locations: Any, make_user: Callable[..., Any]
) -> None:
    ba_b = make_user("branch_admin", "b")
    sa = client_as(users["sa"])
    assert call(sa, "GET", URL).json()["count"] == 6  # all branches, nobody filtered out
    only_b = call(sa, "GET", URL, {"branch": locations["b"].pk}).json()
    assert [r["login_id"] for r in only_b["results"]] == [ba_b.login_id]
    only_a = call(sa, "GET", URL, {"branch": locations["a"].pk}).json()
    assert [r["login_id"] for r in only_a["results"]] == [users["ba"].login_id]
    # roles with a fixed location cannot widen or redirect their scope with the filter
    wa = call(client_as(users["wa"]), "GET", URL, {"branch": locations["b"].pk}).json()
    assert [r["login_id"] for r in wa["results"]] == [users["wa"].login_id]
    ba = call(client_as(users["ba"]), "GET", URL, {"branch": locations["b"].pk}).json()
    assert [r["login_id"] for r in ba["results"]] == [users["ba"].login_id]
    assert call(sa, "GET", URL, {"branch": 0}).status_code == 400


# ---- Day 3 end-of-day fixes (FIX-32..FIX-37) ------------------------------------------------------


def test_removing_front_staff_role_revokes_receive_stock_with_audit(
    users: dict[str, Any], locations: Any
) -> None:  # FIX-32
    sa, fs = client_as(users["sa"]), users["fs"]
    call(sa, "PUT", f"{URL}{fs.pk}/permissions/", {"permissions": ["receive_stock"]})
    fs_client = client_as(fs)
    assert "dispatches.receive" in fs_client.get("/api/v1/auth/me/").json()["permissions"]
    body = {"roles": ["warehouse_admin"], "permanent_location_id": locations["wh"].pk}
    assert call(sa, "PATCH", f"{URL}{fs.pk}/", body).status_code == 200
    assert not UserPermission.objects.filter(user=fs, revoked_at__isnull=True).exists()
    event = AuditEvent.objects.get(action="permission_revoked")
    assert event.before_values == {"permission": "receive_stock"} and event.target_ref == fs.login_id
    assert event.after_values == {"reason": "role change"}
    assert "dispatches.receive" not in fs_client.get("/api/v1/auth/me/").json()["permissions"]


def test_receive_stock_grant_only_counts_for_front_staff_active_role(users: dict[str, Any]) -> None:  # FIX-32
    from roles.permissions import effective_actions

    UserPermission.objects.create(user=users["ba"], permission="receive_stock", granted_by=users["sa"])
    UserPermission.objects.create(user=users["wa"], permission="receive_stock", granted_by=users["sa"])
    assert "dispatches.receive" in effective_actions(users["ba"])  # BA has it by role
    assert "dispatches.receive" not in effective_actions(users["wa"])  # stale grant ignored


@pytest.mark.django_db(transaction=True)
def test_two_super_admins_suspending_each_other_one_wins_no_deadlock(
    users: dict[str, Any], make_user: Callable[..., Any]
) -> None:  # FIX-33
    a, b = users["sa"], make_user("super_admin")
    clients, barrier = {a.pk: client_as(a), b.pk: client_as(b)}, Barrier(2)

    def suspend(pair: tuple[int, User]) -> int:
        actor_pk, target = pair
        try:
            barrier.wait()
            return set_status(clients[actor_pk], target, "suspended").status_code
        finally:
            connection.close()

    with ThreadPoolExecutor(2) as pool:
        codes = sorted(pool.map(suspend, [(a.pk, b), (b.pk, a)]))
    assert codes == [200, 409], codes
    assert User.objects.filter(status=UserStatus.ACTIVE, user_roles__role__code="super_admin").count() == 1


def test_super_admin_cannot_change_own_status_when_another_sa_exists(
    users: dict[str, Any], make_user: Callable[..., Any]
) -> None:  # FIX-36
    make_user("super_admin")
    refused = set_status(client_as(users["sa"]), users["sa"], "suspended")
    assert refused.status_code == 409 and refused.json()["code"] == "conflict"
    assert "own status" in refused.json()["message"]
    users["sa"].refresh_from_db()
    assert users["sa"].status == UserStatus.ACTIVE


def test_sa_with_front_staff_role_and_context_branch_is_not_listed_as_front_staff_at_branch(
    users: dict[str, Any], make_user: Callable[..., Any], locations: Any
) -> None:  # FIX-35
    both = make_user("super_admin")
    call(client_as(users["sa"]), "PATCH", f"{URL}{both.pk}/", {"roles": ["super_admin", "front_staff"]})
    both_client = client_as(both)
    put = call(both_client, "PUT", "/api/v1/working-branch/", {"branch_id": locations["a"].pk})
    assert put.status_code in (200, 204)
    assert call(client_as(users["ba"]), "GET", f"{URL}{both.pk}/").status_code == 404

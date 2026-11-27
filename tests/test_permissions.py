"""B2.4 / B2.6: permission matrix from docs/design/PERMISSION_TABLE.md, branch rules, grants, menu, /me."""

from collections.abc import Callable
from typing import Any

import pytest
from django.contrib.auth.models import AnonymousUser
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import User, UserStatus
from config.errors import ApiError
from roles.models import UserPermission
from roles.permissions import (
    ACTIONS,
    can_act_in,
    effective_actions,
    has_action,
    require_action,
    require_location,
)
from roles.services import assign_roles, role_codes
from tests.conftest import login

pytestmark = [pytest.mark.django_db, pytest.mark.urls("tests.urls")]
SA, WA, BA, FS = "super_admin", "warehouse_admin", "branch_admin", "front_staff"

# Written from the approved table (row numbers in brackets), NOT derived from the code under test.
EXPECTED: dict[str, set[str]] = {
    "users.manage": {SA},  # 4-8
    "users.view": {SA, WA, BA},  # 9 (WA warehouse, BA own branch: OQ-5)
    "branches.manage": {SA},  # 11
    "branches.view": {SA, WA, BA, FS},  # 12
    "working_branch.select": {SA, FS},  # 10
    "items.view": {SA, WA, BA, FS},  # 13
    "items.manage": {SA, WA},  # 15, 17, 18, 43
    "items.view_cost": {SA, WA},  # 14
    "prices.manage": {SA},  # 16 (others only with the Manage prices grant)
    "stock.view": {SA, WA, BA, FS},  # 21
    "stock.lookup_other_branches": {SA, WA, BA, FS},  # 22
    "goods_receipts.manage": {SA, WA},  # 25, 27
    "dispatches.create": {SA, WA},  # 28
    "dispatches.view": {SA, WA, BA, FS},  # 29
    "dispatches.waiting": {SA, BA, FS},  # 30
    "dispatches.receive": {SA, BA},  # 31 (FS only with the Receive stock grant)
    "sales.record": {SA, BA, FS},  # 36, 44
    "activity.view": {SA, WA, BA},  # 41, 45
    "find.use": {SA, WA, BA, FS},  # 13, 22, 46
    "dashboard.view": {SA, WA, BA},  # 40 (FS has no Home tab)
    "sales.cancel": {SA, BA},  # 39
    "items.import": {SA, WA},  # 19, 20
    "shortfalls.resolve": {SA, WA, BA},  # 33-35
    "design_system.view": {SA},  # 50
}
MENUS = {
    FS: ["Sell", "Find", "Stock", "Receive", "Sales"],
    BA: ["Home", "Sell", "Find", "Stock", "Receive"],
    WA: ["Home", "Items", "Receive stock", "Dispatch", "Find"],
    SA: ["Home", "Items", "Warehouse", "Branches", "Users"],
}


def test_expected_matrix_covers_every_action() -> None:
    assert set(EXPECTED) == set(ACTIONS) and len(ACTIONS) == 24


def test_effective_actions_match_the_permission_table_for_every_role(users: dict[str, Any]) -> None:
    for key, role in {"sa": SA, "wa": WA, "ba": BA, "fs": FS}.items():
        allowed = {a for a in ACTIONS if role in EXPECTED[a]}
        assert set(effective_actions(users[key])) == allowed, role
        for action in ACTIONS:
            assert has_action(users[key], action) == (action in allowed), (role, action)
    assert effective_actions(users["sa"]) == ACTIONS  # contract order


@pytest.mark.parametrize("action", ACTIONS)
def test_http_probe_per_action_for_every_role(action: str, users: dict[str, Any]) -> None:
    """The permission class a view declares: allowed role 200, every other role 403, anonymous 401."""
    url = f"/probe/action/{action}/"
    assert APIClient().get(url).status_code == 401
    for key, role in {"sa": SA, "wa": WA, "ba": BA, "fs": FS}.items():
        client = APIClient()
        login(client, users[key])
        response = client.get(url)
        if role in EXPECTED[action]:
            assert response.status_code == 200, (role, action)
        else:
            assert response.status_code == 403, (role, action)
            assert response.json()["code"] == "permission_denied"


def test_action_views_also_need_the_password_change_and_an_active_account(
    make_user: Callable[..., Any],
) -> None:
    pending = make_user("super_admin", status=UserStatus.PENDING_ACTIVATION, must_change_password=True)
    client = APIClient()
    login(client, pending)
    response = client.get("/probe/action/users.manage/")
    assert response.status_code == 403 and response.json()["code"] == "password_change_required"
    assert not has_action(pending, "users.manage")  # service-layer check agrees
    active = make_user("super_admin")
    client = APIClient()
    login(client, active)
    User.objects.filter(pk=active.pk).update(status=UserStatus.SUSPENDED)
    assert client.get("/probe/action/users.manage/").status_code == 401
    assert not has_action(User.objects.get(pk=active.pk), "users.manage")


def test_deny_by_default(users: dict[str, Any], make_user: Callable[..., Any]) -> None:
    assert not has_action(users["sa"], "not.an.action")
    assert not has_action(AnonymousUser(), "items.view")
    assert not has_action(None, "items.view")
    roleless = User.objects.create(login_id="USR-0500", full_name="No role", status=UserStatus.ACTIVE)
    roleless.must_change_password = False
    assert effective_actions(roleless) == [] and not has_action(roleless, "items.view")
    with pytest.raises(ApiError) as exc:
        require_action(users["fs"], "users.manage")
    assert exc.value.status == 403 and exc.value.code == "permission_denied"
    require_action(users["sa"], "users.manage")  # allowed: no exception


# ---- per-person grants (table s3) ------------------------------------------------------------


def grant(user: User, permission: str, by: User) -> UserPermission:
    return UserPermission.objects.create(user=user, permission=permission, granted_by=by)


def test_receive_stock_grant_unlocks_receiving_for_front_staff(users: dict[str, Any]) -> None:
    assert not has_action(users["fs"], "dispatches.receive")
    grant(users["fs"], "receive_stock", users["sa"])
    assert has_action(users["fs"], "dispatches.receive")
    assert not has_action(users["fs"], "dispatches.create") and not has_action(users["fs"], "prices.manage")


def test_manage_prices_grant_works_for_any_role_and_revoke_removes_it(users: dict[str, Any]) -> None:
    for key in ("wa", "ba", "fs"):
        assert not has_action(users[key], "prices.manage")
        row = grant(users[key], "manage_prices", users["sa"])
        assert has_action(users[key], "prices.manage")
        row.revoked_at, row.revoked_by = timezone.now(), users["sa"]
        row.save()
        assert not has_action(users[key], "prices.manage")  # revoked rows are kept but ignored
    assert UserPermission.objects.count() == 3


def test_discount_grant_has_no_mvp_action_and_a_grant_never_widens_branch_scope(
    users: dict[str, Any], locations: dict[str, Any]
) -> None:
    before = effective_actions(users["fs"])
    grant(users["fs"], "discount", users["sa"])
    grant(users["fs"], "receive_stock", users["sa"])
    assert set(effective_actions(users["fs"])) - set(before) == {"dispatches.receive"}
    assert not can_act_in(users["fs"], locations["a"], {})  # no working branch chosen: still no branch


def test_only_one_active_grant_per_person_and_code(users: dict[str, Any]) -> None:
    from django.db import IntegrityError, transaction

    grant(users["fs"], "receive_stock", users["sa"])
    with pytest.raises(IntegrityError), transaction.atomic():
        grant(users["fs"], "receive_stock", users["sa"])
    with pytest.raises(IntegrityError), transaction.atomic():
        grant(users["fs"], "mine_all_mine", users["sa"])


# ---- branch rules (table s2) -----------------------------------------------------------------


def test_branch_rules_for_every_role(users: dict[str, Any], locations: dict[str, Any]) -> None:
    wh, a, b = locations["wh"], locations["a"], locations["b"]
    assert all(can_act_in(users["sa"], loc, {}) for loc in (wh, a, b))  # SA acts everywhere
    assert [can_act_in(users["wa"], loc, {}) for loc in (wh, a, b)] == [True, False, False]
    assert [can_act_in(users["ba"], loc, {}) for loc in (wh, a, b)] == [False, True, False]
    assert [can_act_in(users["fs"], loc, {}) for loc in (wh, a, b)] == [False, False, False]
    chosen = {"working_branch_id": b.pk}
    assert [can_act_in(users["fs"], loc, chosen) for loc in (wh, a, b)] == [False, False, True]
    # BA and WA cannot be redirected by a session value
    assert not can_act_in(users["ba"], b, chosen) and not can_act_in(users["wa"], b, chosen)


def test_wrong_branch_is_refused_with_its_own_code(users: dict[str, Any], locations: dict[str, Any]) -> None:
    with pytest.raises(ApiError) as exc:
        require_location(users["ba"], locations["b"], {})
    assert exc.value.status == 403 and exc.value.code == "wrong_branch"
    require_location(users["ba"], locations["a"], {})  # own branch: no exception


def test_inactive_branch_or_user_cannot_be_acted_in(users: dict[str, Any], locations: dict[str, Any]) -> None:
    locations["a"].is_active = False
    assert not can_act_in(users["sa"], locations["a"], {}) and not can_act_in(users["ba"], locations["a"], {})
    users["ba"].status = UserStatus.SUSPENDED
    assert not can_act_in(users["ba"], locations["b"], {})


# ---- roles ------------------------------------------------------------------------------------


def test_only_super_admins_assign_several_roles(users: dict[str, Any], make_user: Callable[..., Any]) -> None:
    target = make_user("front_staff")
    for key in ("wa", "ba", "fs"):
        with pytest.raises(ApiError) as exc:
            assign_roles(target, [FS, BA], users[key])
        assert exc.value.status == 403
    with pytest.raises(ApiError):
        assign_roles(target, [FS, BA], None)
    with pytest.raises(ApiError):
        assign_roles(target, [], users["sa"])
    assert role_codes(target) == [FS]
    assign_roles(target, [FS, BA], users["sa"])
    assert role_codes(target) == [BA, FS]  # highest authority first; the first is the active role


def test_adding_a_second_role_one_at_a_time_is_refused_for_non_super_admin(
    users: dict[str, Any], make_user: Callable[..., Any]
) -> None:
    target = make_user("front_staff")
    for key in ("wa", "ba", "fs"):
        with pytest.raises(ApiError) as exc:
            assign_roles(target, [BA], users[key])
        assert exc.value.status == 403
        assert role_codes(target) == [FS]


# ---- /me and the allowed menu -----------------------------------------------------------------


@pytest.mark.parametrize("key", ["sa", "wa", "ba", "fs"])
def test_me_returns_roles_permissions_and_menu_per_role(key: str, users: dict[str, Any]) -> None:
    role = {"sa": SA, "wa": WA, "ba": BA, "fs": FS}[key]
    client = APIClient()
    login(client, users[key])
    body = client.get("/api/v1/auth/me/").json()
    assert body["active_role"] == role and body["user"]["roles"] == [role]
    assert set(body["permissions"]) == {a for a in ACTIONS if role in EXPECTED[a]}
    assert [m["label"] for m in body["menu"]] == MENUS[role] and len(body["menu"]) <= 5
    # OQ-23/OQ-25: Home tiles are kept out of the 5-item menu; WA and BA get an Activity tile
    assert [m["label"] for m in body["home_links"]] == {
        SA: ["Activity", "Shortfalls", "Sell", "Find", "Receive", "Sales"],  # SA, BA menus are full
        WA: ["Activity", "Shortfalls"],
        BA: ["Activity", "Shortfalls", "Sales"],
        FS: [],
    }[role]
    assert ("activity.view" in body["permissions"]) == (role != FS)
    assert ("shortfalls.resolve" in body["permissions"]) == (role != FS)
    assert ("design_system.view" in body["permissions"]) == (role == SA)  # DP.1: Super Admin only
    tiles = {m["key"] for m in body["home_links"]}  # FQ-16: a tile only for the holder of its action
    assert ("activity" in tiles) == ("activity.view" in body["permissions"])
    assert ("shortfalls" in tiles) == ("shortfalls.resolve" in body["permissions"])
    assert len(tiles) == len(body["home_links"])  # no duplicates
    assert all(
        set(m) == {"key", "label", "path"} and m["path"].startswith("/")
        for m in body["menu"] + body["home_links"]
    )
    assert body["can_assign_multiple_roles"] is (role == SA)
    assert body["must_pick_branch"] is (role == FS)  # FS has no branch yet; SA is never asked
    assert body["user"]["permissions"] == [] and body["must_change_password"] is False
    assert not any("cost" in k for k in body["user"])


def test_me_working_branch_per_role(users: dict[str, Any], locations: dict[str, Any]) -> None:
    def me(key: str) -> dict[str, Any]:
        client = APIClient()
        login(client, users[key])
        return client.get("/api/v1/auth/me/").json()

    assert me("wa")["working_branch"]["kind"] == "warehouse"
    assert me("ba")["working_branch"]["code"] == "A"
    assert me("fs")["working_branch"] is None and me("sa")["working_branch"] is None
    client = APIClient()
    login(client, users["fs"])
    session = client.session
    session["working_branch_id"] = locations["b"].pk
    session.save()
    assert client.get("/api/v1/auth/me/").json()["working_branch"]["code"] == "B"
    locations["b"].is_active = False
    locations["b"].save()
    assert client.get("/api/v1/auth/me/").json()["working_branch"] is None  # a deactivated branch is dropped


def test_me_shows_per_person_grants_and_effective_permissions(users: dict[str, Any]) -> None:
    grant(users["fs"], "receive_stock", users["sa"])
    client = APIClient()
    login(client, users["fs"])
    body = client.get("/api/v1/auth/me/").json()
    assert body["user"]["permissions"] == ["receive_stock"] and "dispatches.receive" in body["permissions"]


def test_me_for_a_multi_role_user_uses_the_highest_role(
    users: dict[str, Any], make_user: Callable[..., Any]
) -> None:
    both = make_user("front_staff")
    assign_roles(both, [FS, SA], users["sa"])
    client = APIClient()
    login(client, both)
    body = client.get("/api/v1/auth/me/").json()
    assert body["active_role"] == SA and body["user"]["roles"] == [SA, FS]

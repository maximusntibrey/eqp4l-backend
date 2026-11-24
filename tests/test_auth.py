"""B2.3 / B2.6: login, logout, me, CSRF, change password, forced change, rate limit, login log, audit."""

from collections.abc import Callable
from datetime import timedelta
from typing import Any
from unittest import mock

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import LoginEvent, LoginLog, User, UserStatus
from audit.models import AuditEvent
from tests.conftest import PASSWORD, login

pytestmark = [pytest.mark.django_db, pytest.mark.urls("tests.urls")]
LOGIN = "/api/v1/auth/login/"


def post_login(client: APIClient, login_id: str, password: str, ip: str = "10.0.0.1") -> Any:
    token = client.get("/api/v1/auth/csrf/").json()["csrf_token"]
    return client.post(
        LOGIN,
        {"login_id": login_id, "password": password},
        format="json",
        HTTP_X_CSRFTOKEN=token,
        REMOTE_ADDR=ip,
    )


def assert_error(response: Any, status: int, code: str) -> dict[str, Any]:
    body = response.json()
    assert response.status_code == status, body
    assert body["code"] == code
    assert isinstance(body["message"], str)
    assert isinstance(body["errors"], list)
    return body


# ---- success and shape -----------------------------------------------------------------------


def test_login_success_returns_me_and_sets_session(api: APIClient, users: dict[str, Any]) -> None:
    response = login(api, users["ba"])
    assert response.status_code == 200
    body = response.json()
    assert body["user"]["login_id"] == users["ba"].login_id
    assert body["active_role"] == "branch_admin"
    assert body["working_branch"]["code"] == "A"
    assert body["must_change_password"] is False
    assert "sessionid" in api.cookies
    assert api.cookies["sessionid"]["httponly"]
    assert api.get("/api/v1/auth/me/").status_code == 200


def test_login_id_is_case_and_space_insensitive(api: APIClient, users: dict[str, Any]) -> None:
    assert post_login(api, f"  {users['sa'].login_id.lower()} ", PASSWORD).status_code == 200


def test_password_is_hashed_with_argon2_and_never_returned(api: APIClient, users: dict[str, Any]) -> None:
    assert User.objects.get(pk=users["sa"].pk).password.startswith("argon2$")
    assert PASSWORD not in login(api, users["sa"]).content.decode()


def test_login_stamps_last_login_and_logs_success(api: APIClient, users: dict[str, Any]) -> None:
    login(api, users["fs"])
    user = User.objects.get(pk=users["fs"].pk)
    assert user.last_login_at is not None
    row = LoginLog.objects.get(event=LoginEvent.SUCCESS)
    assert row.user_id == user.pk and row.login_id_attempted == user.login_id and row.ip
    assert (
        AuditEvent.objects.filter(action="login_success", actor=user, actor_role="front_staff").count() == 1
    )


# ---- failures --------------------------------------------------------------------------------


def test_wrong_password_is_401_and_logged_without_the_password(api: APIClient, users: dict[str, Any]) -> None:
    response = post_login(api, users["ba"].login_id, "not-the-password")
    assert_error(response, 401, "invalid_credentials")
    row = LoginLog.objects.get(event=LoginEvent.FAILED)
    assert row.failure_reason == "invalid_credentials" and row.user_id == users["ba"].pk
    dump = " ".join(str(v) for v in AuditEvent.objects.values()) + " ".join(
        str(v) for v in LoginLog.objects.values()
    )
    assert "not-the-password" not in dump and PASSWORD not in dump
    assert AuditEvent.objects.filter(action="login_failed", actor=users["ba"]).exists()


def test_unknown_login_id_looks_the_same_as_a_wrong_password(api: APIClient, users: dict[str, Any]) -> None:
    known = post_login(api, users["ba"].login_id, "wrong-password-1").json()
    unknown = post_login(api, "USR-9999", "wrong-password-1").json()
    assert known == unknown
    row = LoginLog.objects.get(login_id_attempted="USR-9999")
    assert row.user_id is None
    assert AuditEvent.objects.get(action="login_failed", actor_login_id="USR-9999").actor_id is None


@pytest.mark.parametrize("status", [UserStatus.SUSPENDED, UserStatus.DEACTIVATED])
def test_inactive_accounts_get_403_account_inactive(
    api: APIClient, make_user: Callable[..., Any], status: str
) -> None:
    user = make_user("front_staff", status=status)
    assert_error(post_login(api, user.login_id, PASSWORD), 403, "account_inactive")
    assert LoginLog.objects.get(event=LoginEvent.FAILED).failure_reason == "account_inactive"
    # a wrong password never reveals the state of the account
    assert_error(post_login(api, user.login_id, "wrong-password-1"), 401, "invalid_credentials")


def test_session_of_a_suspended_user_stops_working_at_once(api: APIClient, users: dict[str, Any]) -> None:
    login(api, users["ba"])
    User.objects.filter(pk=users["ba"].pk).update(status=UserStatus.SUSPENDED)
    assert_error(api.get("/api/v1/auth/me/"), 401, "not_authenticated")


def test_bad_input_is_400_in_the_standard_error_format(api: APIClient) -> None:
    token = api.get("/api/v1/auth/csrf/").json()["csrf_token"]
    response = api.post(LOGIN, {"login_id": ""}, format="json", HTTP_X_CSRFTOKEN=token)
    body = assert_error(response, 400, "validation_error")
    assert {e["field"] for e in body["errors"]} == {"login_id", "password"}


# ---- CSRF ------------------------------------------------------------------------------------


def test_csrf_endpoint_sets_cookie_and_returns_token(api: APIClient) -> None:
    response = api.get("/api/v1/auth/csrf/")
    assert response.status_code == 200
    assert response.json()["csrf_token"] and "csrftoken" in api.cookies


def test_login_without_csrf_token_is_refused(users: dict[str, Any]) -> None:
    client = APIClient(enforce_csrf_checks=True)
    response = client.post(LOGIN, {"login_id": users["sa"].login_id, "password": PASSWORD}, format="json")
    assert_error(response, 403, "csrf_failed")
    assert not LoginLog.objects.exists()


def test_login_with_csrf_token_works_when_checks_are_enforced(users: dict[str, Any]) -> None:
    client = APIClient(enforce_csrf_checks=True)
    assert post_login(client, users["sa"].login_id, PASSWORD).status_code == 200


def test_logout_and_password_change_need_the_csrf_header(users: dict[str, Any]) -> None:
    client = APIClient(enforce_csrf_checks=True)
    assert post_login(client, users["sa"].login_id, PASSWORD).status_code == 200
    assert_error(client.post("/api/v1/auth/logout/"), 403, "csrf_failed")
    assert_error(
        client.post(
            "/api/v1/auth/password/", {"current_password": PASSWORD, "new_password": "x" * 12}, format="json"
        ),
        403,
        "csrf_failed",
    )
    assert client.get("/api/v1/auth/me/").status_code == 200  # still logged in


# ---- logout and me ---------------------------------------------------------------------------


def test_logout_ends_the_session_and_is_logged_and_audited(api: APIClient, users: dict[str, Any]) -> None:
    login(api, users["sa"])
    assert api.post("/api/v1/auth/logout/").status_code == 204
    assert_error(api.get("/api/v1/auth/me/"), 401, "not_authenticated")
    assert LoginLog.objects.filter(event=LoginEvent.LOGOUT, user=users["sa"]).count() == 1
    assert AuditEvent.objects.filter(action="logout", actor=users["sa"]).count() == 1


def test_anonymous_is_401_on_protected_auth_endpoints(api: APIClient) -> None:
    assert_error(api.get("/api/v1/auth/me/"), 401, "not_authenticated")
    assert_error(api.post("/api/v1/auth/logout/"), 401, "not_authenticated")
    assert_error(api.post("/api/v1/auth/password/", {}, format="json"), 401, "not_authenticated")
    assert api.get("/api/v1/auth/me/")["WWW-Authenticate"] == "Session"


def test_wrong_method_uses_the_standard_error(api: APIClient) -> None:
    assert_error(api.get(LOGIN), 405, "method_not_allowed")


# ---- rate limit (OQ-13) ----------------------------------------------------------------------


def fail_times(client: APIClient, login_id: str, n: int, ip: str = "10.0.0.1") -> None:
    for _ in range(n):
        assert post_login(client, login_id, "wrong-password-1", ip).status_code == 401


def test_five_failures_then_429_with_retry_after_even_for_the_right_password(
    api: APIClient, users: dict[str, Any]
) -> None:
    uid = users["ba"].login_id
    fail_times(api, uid, 5)
    response = post_login(api, uid, PASSWORD)
    assert_error(response, 429, "rate_limited")
    assert 0 < int(response["Retry-After"]) <= 15 * 60
    assert api.get("/api/v1/auth/me/").status_code == 401  # not logged in
    blocked = LoginLog.objects.filter(failure_reason="rate_limited")
    assert blocked.count() == 1


def test_four_failures_do_not_lock(api: APIClient, users: dict[str, Any]) -> None:
    fail_times(api, users["ba"].login_id, 4)
    assert post_login(api, users["ba"].login_id, PASSWORD).status_code == 200


def test_lock_is_per_login_id_and_ip(api: APIClient, users: dict[str, Any]) -> None:
    fail_times(api, users["ba"].login_id, 5)
    assert_error(post_login(api, users["ba"].login_id, PASSWORD), 429, "rate_limited")
    assert post_login(api, users["ba"].login_id, PASSWORD, ip="10.0.0.2").status_code == 200  # other IP
    assert post_login(APIClient(), users["sa"].login_id, PASSWORD).status_code == 200  # other login ID


def test_lock_lasts_fifteen_minutes_from_the_last_failure_and_blocked_tries_do_not_extend_it(
    api: APIClient, users: dict[str, Any]
) -> None:
    uid = users["ba"].login_id
    fail_times(api, uid, 5)
    now = timezone.now()
    with mock.patch("django.utils.timezone.now", return_value=now + timedelta(minutes=10)):
        response = post_login(api, uid, PASSWORD)  # blocked, logged as rate_limited
        assert_error(response, 429, "rate_limited")
        assert 250 <= int(response["Retry-After"]) <= 300
    with mock.patch("django.utils.timezone.now", return_value=now + timedelta(minutes=16)):
        assert post_login(api, uid, PASSWORD).status_code == 200


def test_success_clears_earlier_failures(api: APIClient, users: dict[str, Any]) -> None:
    uid = users["ba"].login_id
    fail_times(api, uid, 4)
    assert post_login(api, uid, PASSWORD).status_code == 200
    fail_times(APIClient(), uid, 4)  # four more is still below the limit
    assert post_login(APIClient(), uid, PASSWORD).status_code == 200


# ---- forced password change (C5, OQ-22) ------------------------------------------------------


def one_time_user(make_user: Callable[..., Any], role: str = "front_staff") -> Any:
    user = make_user(
        role, status=UserStatus.PENDING_ACTIVATION, must_change_password=True, issued=timezone.now()
    )
    return user


def test_new_user_logs_in_with_the_one_time_password_and_is_forced_to_change_it(
    api: APIClient, make_user: Callable[..., Any]
) -> None:
    user = one_time_user(make_user)
    user.set_password(user.otp)
    user.save()
    response = post_login(api, user.login_id, user.otp)
    assert response.status_code == 200
    assert (
        response.json()["must_change_password"] is True
        and response.json()["user"]["status"] == "pending_activation"
    )
    assert api.get("/api/v1/auth/me/").status_code == 200  # allowed while pending
    assert_error(api.get("/probe/default/"), 403, "password_change_required")
    assert_error(api.post("/probe/default/", {}, format="json"), 403, "password_change_required")
    assert api.get("/api/v1/auth/csrf/").status_code == 200


def test_changing_the_password_activates_the_account_and_opens_the_api(
    api: APIClient, make_user: Callable[..., Any]
) -> None:
    user = one_time_user(make_user)
    login(api, user)
    response = api.post(
        "/api/v1/auth/password/",
        {"current_password": PASSWORD, "new_password": "a-brand-new-secret"},
        format="json",
    )
    assert response.status_code == 204
    user.refresh_from_db()
    assert user.status == UserStatus.ACTIVE and user.must_change_password is False
    assert user.one_time_password_issued_at is None and user.check_password("a-brand-new-secret")
    assert api.get("/probe/default/").status_code == 200  # same session still valid
    event = AuditEvent.objects.get(action="password_changed")
    assert event.actor_id == user.pk and event.after_values == {"forced_change": True}
    assert "a-brand-new-secret" not in str(event.after_values)
    api.post("/api/v1/auth/logout/")
    assert post_login(api, user.login_id, "a-brand-new-secret").status_code == 200
    assert_error(post_login(APIClient(), user.login_id, PASSWORD), 401, "invalid_credentials")


def test_expired_one_time_password_is_refused_after_72_hours(
    api: APIClient, make_user: Callable[..., Any]
) -> None:
    user = make_user("front_staff", status=UserStatus.PENDING_ACTIVATION, must_change_password=True)
    User.objects.filter(pk=user.pk).update(one_time_password_issued_at=timezone.now() - timedelta(hours=73))
    assert_error(post_login(api, user.login_id, PASSWORD), 401, "invalid_credentials")
    assert LoginLog.objects.get().failure_reason == "one_time_password_expired"
    User.objects.filter(pk=user.pk).update(one_time_password_issued_at=timezone.now() - timedelta(hours=71))
    assert post_login(APIClient(), user.login_id, PASSWORD).status_code == 200


def test_password_change_validation(api: APIClient, users: dict[str, Any]) -> None:
    login(api, users["sa"])
    url = "/api/v1/auth/password/"

    def change(current: str, new: str) -> Any:
        return api.post(url, {"current_password": current, "new_password": new}, format="json")

    body = assert_error(change("wrong-current-pass", "a-long-enough-one"), 400, "validation_error")
    assert body["errors"][0]["field"] == "current_password"
    body = assert_error(change(PASSWORD, "short-pw"), 400, "validation_error")
    assert body["errors"][0]["field"] == "new_password"
    body = assert_error(change(PASSWORD, PASSWORD), 400, "validation_error")
    assert body["errors"][0]["field"] == "new_password"
    assert_error(api.post(url, {}, format="json"), 400, "validation_error")
    assert change(PASSWORD, "0123456789").status_code == 204  # exactly 10 characters is accepted
    assert AuditEvent.objects.filter(action="password_changed").count() == 1  # refusals write nothing


def test_changing_the_password_ends_other_sessions(users: dict[str, Any]) -> None:
    first, second = APIClient(), APIClient()
    login(first, users["sa"])
    login(second, users["sa"])
    assert (
        second.post(
            "/api/v1/auth/password/",
            {"current_password": PASSWORD, "new_password": "another-long-one"},
            format="json",
        ).status_code
        == 204
    )
    assert second.get("/api/v1/auth/me/").status_code == 200
    assert first.get("/api/v1/auth/me/").status_code == 401


def test_login_never_reuses_a_session_key(api: APIClient, users: dict[str, Any]) -> None:
    api.get("/api/v1/auth/csrf/")
    login(api, users["sa"])
    first = api.cookies["sessionid"].value
    api.post("/api/v1/auth/logout/")
    login(api, users["sa"])
    assert api.cookies["sessionid"].value != first


def test_login_replaces_a_planted_anonymous_session_key(api: APIClient, users: dict[str, Any]) -> None:
    from importlib import import_module

    from django.conf import settings

    store = import_module(settings.SESSION_ENGINE).SessionStore()
    store["planted"] = "attacker"
    store.save()
    planted = store.session_key
    api.cookies[settings.SESSION_COOKIE_NAME] = planted
    assert login(api, users["sa"]).status_code == 200
    assert api.cookies[settings.SESSION_COOKIE_NAME].value != planted
    assert not store.exists(planted)  # the planted key is dead server-side too


@pytest.mark.django_db(transaction=True)
def test_ten_concurrent_wrong_logins_allow_at_most_five_failures_then_429(
    users: dict[str, Any],
) -> None:
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from django.db import connection

    uid, barrier = users["ba"].login_id, Barrier(10)
    clients = [APIClient() for _ in range(10)]
    tokens = [c.get("/api/v1/auth/csrf/").json()["csrf_token"] for c in clients]

    def attempt(i: int) -> int:
        try:
            barrier.wait()
            return int(
                clients[i]
                .post(
                    LOGIN,
                    {"login_id": uid, "password": "wrong-password-1"},
                    format="json",
                    HTTP_X_CSRFTOKEN=tokens[i],
                    REMOTE_ADDR="10.0.0.9",
                )
                .status_code
            )
        finally:
            connection.close()

    with ThreadPoolExecutor(10) as pool:
        codes = list(pool.map(attempt, range(10)))
    assert codes.count(401) == 5 and codes.count(429) == 5, codes


def test_sixth_wrong_current_password_gives_429_and_is_logged_without_the_password(
    api: APIClient, users: dict[str, Any]
) -> None:
    login(api, users["sa"])
    url = "/api/v1/auth/password/"
    body = {"current_password": "wrong-current-pw", "new_password": "a-long-enough-one"}
    for _ in range(5):
        assert_error(api.post(url, body, format="json"), 400, "validation_error")
    response = api.post(url, body, format="json")
    assert_error(response, 429, "rate_limited")
    assert int(response["Retry-After"]) > 0
    # even the right current password is refused while locked; the password is unchanged
    ok = api.post(url, {"current_password": PASSWORD, "new_password": "a-long-enough-one"}, format="json")
    assert_error(ok, 429, "rate_limited")
    users["sa"].refresh_from_db()
    assert users["sa"].check_password(PASSWORD)
    events = AuditEvent.objects.filter(action="password_change_failed")
    assert events.count() == 7
    assert "wrong-current-pw" not in str(list(events.values())) + str(list(LoginLog.objects.values()))
    # a login failure counter is separate: logging in still works
    assert post_login(APIClient(), users["sa"].login_id, PASSWORD).status_code == 200

"""B3.1: working-branch selection and switching (table row 10, OQ-12): scoping, 403s, switch log, audit."""

from typing import Any

import pytest

from audit.models import AuditEvent
from branch_access.models import SwitchLog
from branches.models import Location
from tests.api import call, client_as

pytestmark = pytest.mark.django_db
URL = "/api/v1/working-branch/"


def test_front_staff_picks_any_active_branch_and_me_follows(users: dict[str, Any], locations: Any) -> None:
    client = client_as(users["fs"])
    assert call(client, "GET", URL).json() == {"working_branch": None}
    assert client.get("/api/v1/auth/me/").json()["working_branch"] is None
    response = call(client, "PUT", URL, {"branch_id": locations["a"].pk})
    assert response.status_code == 200
    assert response.json()["working_branch"]["code"] == "A"
    assert call(client, "GET", URL).json()["working_branch"]["id"] == locations["a"].pk
    assert client.get("/api/v1/auth/me/").json()["working_branch"]["id"] == locations["a"].pk
    # switching to another branch replaces it
    assert call(client, "PUT", URL, {"branch_id": locations["b"].pk}).json()["working_branch"]["code"] == "B"


def test_every_switch_writes_switch_log_and_audit_and_a_repeat_writes_nothing(
    users: dict[str, Any], locations: Any
) -> None:
    client = client_as(users["fs"])
    a, b = locations["a"], locations["b"]
    for target in (a, b, b, a):
        assert call(client, "PUT", URL, {"branch_id": target.pk}).status_code == 200
    logs = list(SwitchLog.objects.filter(user=users["fs"]).order_by("id"))
    assert [(x.from_location_id, x.to_location_id) for x in logs] == [
        (None, a.pk),
        (a.pk, b.pk),
        (b.pk, a.pk),
    ]  # the repeat of b is not a switch
    events = list(AuditEvent.objects.filter(action="working_branch_switched").order_by("id"))
    assert len(events) == 3
    assert events[1].actor_id == users["fs"].pk and events[1].actor_role == "front_staff"
    assert events[1].before_values == {"location_id": a.pk} and events[1].after_values == {
        "location_id": b.pk
    }
    assert events[1].location_id == b.pk and events[1].target_ref == "B"


def test_super_admin_may_pick_an_optional_context_branch(users: dict[str, Any], locations: Any) -> None:
    client = client_as(users["sa"])
    assert call(client, "GET", URL).json() == {"working_branch": None}
    assert call(client, "PUT", URL, {"branch_id": locations["b"].pk}).status_code == 200
    assert SwitchLog.objects.filter(user=users["sa"]).count() == 1
    assert AuditEvent.objects.get(action="working_branch_switched").actor_role == "super_admin"


@pytest.mark.parametrize("key", ["ba", "wa"])
def test_fixed_location_roles_get_403_and_cannot_redirect_their_scope(
    key: str, users: dict[str, Any], locations: Any
) -> None:
    client = client_as(users[key])
    for method in ("GET", "PUT"):
        response = call(client, method, URL, {"branch_id": locations["b"].pk} if method == "PUT" else None)
        assert response.status_code == 403 and response.json()["code"] == "permission_denied"
    assert not SwitchLog.objects.exists() and not AuditEvent.objects.filter(action="working_branch_switched")
    expected = locations["a"].pk if key == "ba" else locations["wh"].pk
    assert client.get("/api/v1/auth/me/").json()["working_branch"]["id"] == expected  # permanent location


@pytest.mark.parametrize("bad", ["warehouse", "inactive", "missing", "text", "none"])
def test_bad_branch_is_refused_with_the_standard_error_and_nothing_is_logged(
    bad: str, users: dict[str, Any], locations: Any
) -> None:
    inactive = Location.objects.create(kind="branch", code="Z", name="Closed", is_active=False)
    value = {
        "warehouse": locations["wh"].pk,
        "inactive": inactive.pk,
        "missing": 99999,
        "text": "abc",
        "none": None,
    }[bad]
    response = call(client_as(users["fs"]), "PUT", URL, {"branch_id": value})
    body = response.json()
    assert response.status_code == 400 and body["code"] == "validation_error"
    assert body["errors"][0]["field"] == "branch_id"
    assert not SwitchLog.objects.exists()


def test_missing_body_field_and_missing_key_are_400(users: dict[str, Any]) -> None:
    client = client_as(users["fs"])
    assert call(client, "PUT", URL, {}).status_code == 400
    response = call(client, "PUT", URL, {"branch_id": 1}, key=False)
    assert response.status_code == 400 and response.json()["errors"][0]["field"] == "Idempotency-Key"
    assert call(client, "PUT", URL, {"branch_id": 1}, key="not-a-uuid").status_code == 400


def test_a_branch_deactivated_after_the_choice_stops_being_the_working_branch(
    users: dict[str, Any], locations: Any
) -> None:
    client = client_as(users["fs"])
    call(client, "PUT", URL, {"branch_id": locations["a"].pk})
    Location.objects.filter(pk=locations["a"].pk).update(is_active=False)
    assert call(client, "GET", URL).json() == {"working_branch": None}
    assert call(client, "PUT", URL, {"branch_id": locations["a"].pk}).status_code == 400


def test_each_session_has_its_own_working_branch(users: dict[str, Any], locations: Any) -> None:
    one, two = client_as(users["fs"]), client_as(users["fs"])
    call(one, "PUT", URL, {"branch_id": locations["a"].pk})
    assert call(two, "GET", URL).json() == {"working_branch": None}


def test_logging_out_forgets_the_working_branch(users: dict[str, Any], locations: Any) -> None:
    client = client_as(users["fs"])
    call(client, "PUT", URL, {"branch_id": locations["a"].pk})
    assert call(client, "POST", "/api/v1/auth/logout/", key=False).status_code == 204
    fresh = client_as(users["fs"])
    assert call(fresh, "GET", URL).json() == {"working_branch": None}


def test_same_key_replays_the_first_response_without_a_second_switch(
    users: dict[str, Any], locations: Any
) -> None:
    client = client_as(users["fs"])
    first = call(
        client, "PUT", URL, {"branch_id": locations["a"].pk}, key="3f2504e0-4f89-41d3-9a0c-0305e82c3301"
    )
    again = call(
        client, "PUT", URL, {"branch_id": locations["a"].pk}, key="3f2504e0-4f89-41d3-9a0c-0305e82c3301"
    )
    assert first.status_code == again.status_code == 200 and first.json() == again.json()
    assert SwitchLog.objects.count() == 1
    clash = call(
        client, "PUT", URL, {"branch_id": locations["b"].pk}, key="3f2504e0-4f89-41d3-9a0c-0305e82c3301"
    )
    assert clash.status_code == 409 and clash.json()["code"] == "idempotency_conflict"
    assert SwitchLog.objects.count() == 1


def test_must_pick_branch_flag_per_role_and_login(users: dict[str, Any], locations: Any) -> None:
    def me(key: str) -> dict[str, Any]:
        return dict(client_as(users[key]).get("/api/v1/auth/me/").json())

    assert me("sa")["must_pick_branch"] is False  # never asked, with or without a branch
    assert me("ba")["must_pick_branch"] is False and me("wa")["must_pick_branch"] is False
    fs = client_as(users["fs"])
    assert fs.get("/api/v1/auth/me/").json()["must_pick_branch"] is True
    call(fs, "PUT", URL, {"branch_id": locations["a"].pk})
    assert fs.get("/api/v1/auth/me/").json()["must_pick_branch"] is False
    Location.objects.filter(pk=locations["a"].pk).update(is_active=False)
    assert fs.get("/api/v1/auth/me/").json()["must_pick_branch"] is True  # chosen branch no longer usable
    # the login response carries the same flags
    login_body = client_as(users["sa"]).get("/api/v1/auth/me/").json()
    assert login_body["can_assign_multiple_roles"] is True
    assert me("fs")["can_assign_multiple_roles"] is False and me("ba")["can_assign_multiple_roles"] is False

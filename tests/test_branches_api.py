"""B3.2: branch management API (table rows 11, 12): create, edit, deactivate with history kept."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from typing import Any

import pytest
from django.db import connection
from rest_framework.test import APIClient

from audit.models import AuditEvent
from branches.models import Location
from tests.api import call, client_as

pytestmark = pytest.mark.django_db
URL = "/api/v1/branches/"
LOCATION_KEYS = {"id", "kind", "code", "name", "is_active", "created_at", "updated_at"}


def test_everyone_lists_active_locations_in_the_standard_envelope(
    users: dict[str, Any], locations: Any
) -> None:
    Location.objects.create(kind="branch", code="Z", name="Closed", is_active=False)
    for key in ("wa", "ba", "fs"):  # is_active=false is ignored for everyone but the Super Admin
        body = call(client_as(users[key]), "GET", URL, {"is_active": "false"}).json()
        assert set(body) == {"count", "page", "page_size", "next", "previous", "results"}
        assert body["page"] == 1 and body["page_size"] == 25
        assert {r["code"] for r in body["results"]} == {"WH", "A", "B"}  # inactive ones are never shown
        assert all(set(r) == LOCATION_KEYS for r in body["results"])


def test_only_super_admin_may_see_deactivated_branches(users: dict[str, Any], locations: Any) -> None:
    closed = Location.objects.create(kind="branch", code="Z", name="Closed", is_active=False)
    sa = client_as(users["sa"])
    assert call(sa, "GET", URL, {"is_active": "false"}).json()["count"] == 1
    assert call(sa, "GET", URL).json()["count"] == 4
    assert call(sa, "GET", f"{URL}{closed.pk}/").status_code == 200
    ba = client_as(users["ba"])
    assert call(ba, "GET", f"{URL}{closed.pk}/").status_code == 404


def test_kind_filter_paging_and_bad_query(users: dict[str, Any], locations: Any) -> None:
    sa = client_as(users["sa"])
    assert [r["code"] for r in call(sa, "GET", URL, {"kind": "warehouse"}).json()["results"]] == ["WH"]
    page = call(sa, "GET", URL, {"page_size": 2}).json()
    assert page["count"] == 3 and len(page["results"]) == 2 and page["next"]
    response = call(sa, "GET", URL, {"kind": "moon"})
    assert response.status_code == 400 and response.json()["errors"][0]["field"] == "kind"
    assert call(sa, "GET", URL, {"page": 9}).status_code == 404


def test_super_admin_creates_a_branch_and_it_is_audited(users: dict[str, Any], locations: Any) -> None:
    response = call(client_as(users["sa"]), "POST", URL, {"code": "  C  ", "name": "Branch C"})
    body = response.json()
    assert response.status_code == 201 and set(body) == LOCATION_KEYS
    assert (body["kind"], body["code"], body["name"], body["is_active"]) == ("branch", "C", "Branch C", True)
    created = Location.objects.get(pk=body["id"])
    assert created.created_by_id == users["sa"].pk
    event = AuditEvent.objects.get(action="branch_created")
    assert (event.actor_id, event.actor_role, event.target_ref) == (users["sa"].pk, "super_admin", "C")
    assert event.after_values == {"code": "C", "name": "Branch C", "is_active": True}
    assert call(client_as(users["ba"]), "GET", f"{URL}{created.pk}/").status_code == 200  # visible to all


@pytest.mark.parametrize(
    ("payload", "status", "code", "field"),
    [
        ({"code": "a", "name": "Other"}, 409, "conflict", "code"),  # case-insensitive duplicate
        ({"code": "N", "name": "branch a"}, 409, "conflict", "name"),
        ({"name": "No code"}, 400, "validation_error", "code"),
        ({"code": "N"}, 400, "validation_error", "name"),
        ({"code": "   ", "name": "Blank"}, 400, "validation_error", "code"),
        ({"code": "X" * 21, "name": "Long code"}, 400, "validation_error", "code"),
        ({"code": "N", "name": "X" * 101}, 400, "validation_error", "name"),
    ],
)
def test_create_rejects_bad_input_with_the_standard_error(
    payload: dict[str, Any], status: int, code: str, field: str, users: dict[str, Any], locations: Any
) -> None:
    response = call(client_as(users["sa"]), "POST", URL, payload)
    body = response.json()
    assert response.status_code == status and body["code"] == code
    assert body["errors"][0]["field"] == field
    assert Location.objects.count() == 3 and not AuditEvent.objects.filter(action="branch_created")


def test_edit_changes_name_and_code_and_keeps_the_kind(users: dict[str, Any], locations: Any) -> None:
    sa = client_as(users["sa"])
    response = call(sa, "PATCH", f"{URL}{locations['a'].pk}/", {"name": "Accra Central", "kind": "warehouse"})
    assert response.status_code == 200 and response.json()["name"] == "Accra Central"
    assert response.json()["kind"] == "branch" and response.json()["code"] == "A"
    event = AuditEvent.objects.get(action="branch_updated")
    assert event.before_values["name"] == "Branch A" and event.after_values["name"] == "Accra Central"  # type: ignore[index]
    assert (
        call(sa, "PATCH", f"{URL}{locations['a'].pk}/", {"code": "A"}).status_code == 200
    )  # own value is no clash


def test_edit_rejects_duplicates_empty_bodies_and_unknown_branches(
    users: dict[str, Any], locations: Any
) -> None:
    sa = client_as(users["sa"])
    assert call(sa, "PATCH", f"{URL}{locations['a'].pk}/", {"name": "Branch B"}).status_code == 409
    assert call(sa, "PATCH", f"{URL}{locations['a'].pk}/", {}).status_code == 400
    assert call(sa, "PATCH", f"{URL}{locations['a'].pk}/", {"kind": "branch"}).status_code == 400
    assert call(sa, "PATCH", f"{URL}99999/", {"name": "x"}).status_code == 404
    assert not AuditEvent.objects.filter(action="branch_updated")


def test_deactivate_keeps_history_and_activate_restores(users: dict[str, Any], locations: Any) -> None:
    sa, ba = client_as(users["sa"]), client_as(users["ba"])
    a = locations["a"]
    response = call(sa, "POST", f"{URL}{a.pk}/deactivate/")
    assert response.status_code == 200 and response.json()["is_active"] is False
    assert Location.objects.filter(pk=a.pk).exists()  # never deleted
    assert AuditEvent.objects.get(action="branch_deactivated").after_values["is_active"] is False  # type: ignore[index]
    assert "A" not in [r["code"] for r in call(ba, "GET", URL).json()["results"]]
    response = call(sa, "POST", f"{URL}{a.pk}/activate/")
    assert response.status_code == 200 and response.json()["is_active"] is True
    assert AuditEvent.objects.filter(action="branch_activated").count() == 1


def test_state_conflicts_on_deactivate_and_activate(users: dict[str, Any], locations: Any) -> None:
    sa = client_as(users["sa"])
    warehouse = call(sa, "POST", f"{URL}{locations['wh'].pk}/deactivate/")
    assert warehouse.status_code == 409 and warehouse.json()["code"] == "invalid_status_transition"
    assert call(sa, "POST", f"{URL}{locations['a'].pk}/activate/").status_code == 409  # already active
    call(sa, "POST", f"{URL}{locations['a'].pk}/deactivate/")
    assert call(sa, "POST", f"{URL}{locations['a'].pk}/deactivate/").status_code == 409  # already off
    assert call(sa, "POST", f"{URL}99999/deactivate/").status_code == 404
    assert Location.objects.get(pk=locations["wh"].pk).is_active


def test_deactivated_branch_blocks_acting_in_it_but_not_reading_history(
    users: dict[str, Any], locations: Any
) -> None:
    from roles.permissions import can_act_in

    sa = client_as(users["sa"])
    call(sa, "POST", f"{URL}{locations['a'].pk}/deactivate/")
    a = Location.objects.get(pk=locations["a"].pk)
    assert not can_act_in(users["ba"], a, {}) and not can_act_in(users["sa"], a, {})


def test_same_key_creates_one_branch_and_replays_the_response(users: dict[str, Any], locations: Any) -> None:
    sa = client_as(users["sa"])
    key = "9b2d0f0e-6a1c-4c1e-8f43-1a1b2c3d4e5f"
    first = call(sa, "POST", URL, {"code": "C", "name": "Branch C"}, key=key)
    again = call(sa, "POST", URL, {"code": "C", "name": "Branch C"}, key=key)
    assert (first.status_code, again.status_code) == (201, 201) and first.json() == again.json()
    assert Location.objects.filter(code="C").count() == 1
    assert AuditEvent.objects.filter(action="branch_created").count() == 1
    clash = call(sa, "POST", URL, {"code": "D", "name": "Branch D"}, key=key)
    assert clash.status_code == 409 and clash.json()["code"] == "idempotency_conflict"


def test_another_user_cannot_replay_a_stored_response(users: dict[str, Any], locations: Any) -> None:
    key = "6f1d1d9a-5f0b-4b7e-9d52-0a0b0c0d0e0f"
    call(client_as(users["sa"]), "POST", URL, {"code": "C", "name": "Branch C"}, key=key)
    other = call(client_as(users["ba"]), "POST", URL, {"code": "C", "name": "Branch C"}, key=key)
    assert other.status_code == 403  # refused by role, never served from the other user's record


@pytest.mark.django_db(transaction=True)
def test_two_simultaneous_creates_of_the_same_code_exactly_one_wins(
    users: dict[str, Any], locations: Any
) -> None:
    clients = [client_as(users["sa"]) for _ in range(2)]
    barrier = Barrier(2)

    def create(client: APIClient) -> int:
        try:
            barrier.wait()
            return int(call(client, "POST", URL, {"code": "RACE", "name": "Race branch"}).status_code)
        finally:
            connection.close()

    with ThreadPoolExecutor(2) as pool:
        codes = sorted(pool.map(create, clients))
    assert codes == [201, 409], codes
    assert Location.objects.filter(code="RACE").count() == 1


def test_super_admin_sees_all_branches_by_default_and_one_with_the_branch_filter(
    users: dict[str, Any], locations: Any
) -> None:
    sa = client_as(users["sa"])
    assert call(sa, "GET", URL).json()["count"] == 3
    one = call(sa, "GET", URL, {"branch": locations["b"].pk}).json()
    assert [r["code"] for r in one["results"]] == ["B"]
    ba = call(client_as(users["ba"]), "GET", URL, {"branch": locations["b"].pk}).json()
    assert ba["count"] == 3  # ignored for everyone but the Super Admin

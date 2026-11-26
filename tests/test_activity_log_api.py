"""A.1 to A.3: activity log pagination, filters, search, ordering, CSV export and the menu entry."""

import csv
import io
from datetime import timedelta
from typing import Any

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from audit import views
from audit.models import AuditEvent
from roles.menu import home_links_for, menu_for
from tests.api import call, client_as

pytestmark = pytest.mark.django_db
URL = "/api/v1/activity-log/"
EXPORT = f"{URL}export/"
COLUMNS = [
    "occurred_at", "user_login_id", "user_role", "branch_name", "action", "target_type", "target_ref",
    "is_self_approval",
]  # fmt: skip


@pytest.fixture
def events(locations: dict[str, Any], users: dict[str, Any]) -> list[AuditEvent]:
    """Six events: three in branch A, two in the warehouse, one with no location."""
    now = timezone.now()
    spec = [
        ("alpha_done", "item", "SKU-1", "a", "BA-0001", 5),
        ("beta_done", "item", "SKU-2", "a", "BA-0002", 4),
        ("gamma_done", "location", "A", "a", "BA-0001", 3),
        ("alpha_done", "dispatch", "TRF-9", "wh", "WA-0001", 2),
        ("delta_done", "item", "SKU-3", "wh", "WA-0001", 1),
        ("zeta_done", "user", "USR-1", None, "SA-0001", 0),
    ]
    return [
        AuditEvent.objects.create(
            action=action,
            target_type=target_type,
            target_ref=ref,
            location=locations[loc] if loc else None,
            actor_login_id=login,
            occurred_at=now - timedelta(minutes=minutes),
            after_values={"unit_cost": "SECRET-COST-77"},
        )
        for action, target_type, ref, loc, login, minutes in spec
    ]


def results(client: APIClient, **params: Any) -> list[dict[str, Any]]:
    response = call(client, "GET", URL, {"page_size": 100, **params})
    assert response.status_code == 200, response.content
    return response.json()["results"]


def csv_rows(response: Any) -> list[list[str]]:
    return list(csv.reader(io.StringIO(response.content.decode())))


def test_pagination_has_a_max_page_size(users: dict[str, Any], events: Any) -> None:
    sa = client_as(users["sa"])
    for i in range(120):
        AuditEvent.objects.create(action=f"bulk_{i}", location=None)
    first = call(sa, "GET", URL, {"page_size": 1000}).json()
    assert first["page_size"] == 100 and len(first["results"]) == 100 and first["next"]
    second = call(sa, "GET", URL, {"page_size": 100, "page": 2}).json()
    assert second["page"] == 2 and second["count"] == first["count"]
    assert {r["id"] for r in first["results"]}.isdisjoint(r["id"] for r in second["results"])
    assert call(sa, "GET", URL, {"page": 999}).status_code == 404


def test_filter_by_target_type_and_combined_filters(users: dict[str, Any], events: Any) -> None:
    sa = client_as(users["sa"])
    assert {r["target_ref"] for r in results(sa, target_type="item")} == {"SKU-1", "SKU-2", "SKU-3"}
    both = results(sa, target_type="item", action="alpha_done")
    assert [r["target_ref"] for r in both] == ["SKU-1"]
    assert results(sa, target_type="nothing") == []
    assert call(sa, "GET", URL, {"target_type": "x" * 41}).status_code == 400


def test_search_covers_metadata_only(users: dict[str, Any], events: Any) -> None:
    sa = client_as(users["sa"])
    assert {r["target_ref"] for r in results(sa, search="ALPHA")} == {"SKU-1", "TRF-9"}  # case-insensitive
    assert [r["target_ref"] for r in results(sa, search="sku-3")] == ["SKU-3"]
    assert {r["user_login_id"] for r in results(sa, search="BA-0001")} == {"BA-0001"}
    assert results(sa, search="SECRET-COST-77") == []  # stored values are never searched
    assert results(sa, search="no-such-thing") == []
    assert call(sa, "GET", URL, {"search": "x" * 101}).status_code == 400


def test_search_stays_inside_the_callers_scope(users: dict[str, Any], events: Any) -> None:
    ba, wa = client_as(users["ba"]), client_as(users["wa"])
    assert {r["target_ref"] for r in results(ba, search="alpha")} == {"SKU-1"}  # TRF-9 is the warehouse's
    assert {r["target_ref"] for r in results(wa, search="alpha")} == {"TRF-9"}
    assert results(ba, search="zeta") == []  # no-location events: Super Admin only


def test_default_order_is_newest_first(users: dict[str, Any], events: Any) -> None:
    sa = client_as(users["sa"])
    assert [r["target_ref"] for r in results(sa, action="alpha_done")] == ["TRF-9", "SKU-1"]
    assert results(sa, search="_done")[0]["target_ref"] == "USR-1"


@pytest.mark.parametrize(
    ("ordering", "key", "reverse"),
    [
        ("timestamp", "occurred_at", False),
        ("-timestamp", "occurred_at", True),
        ("user", "user_login_id", False),
        ("-user", "user_login_id", True),
        ("action", "action", False),
        ("-action", "action", True),
    ],
)
def test_ordering(ordering: str, key: str, reverse: bool, users: dict[str, Any], events: Any) -> None:
    rows = results(client_as(users["sa"]), ordering=ordering, search="_done")
    values = [r[key] for r in rows]
    assert len(values) == 6 and values == sorted(values, reverse=reverse)


def test_bad_ordering_is_a_standard_400(users: dict[str, Any], events: Any) -> None:
    response = call(client_as(users["sa"]), "GET", URL, {"ordering": "password"})
    assert response.status_code == 400 and response.json()["errors"][0]["field"] == "ordering"


def test_export_returns_csv_with_the_same_filters_and_scope(users: dict[str, Any], events: Any) -> None:
    sa = client_as(users["sa"])
    response = call(sa, "GET", EXPORT, {"target_type": "item", "ordering": "timestamp"})
    assert response.status_code == 200 and response["Content-Type"].startswith("text/csv")
    assert "attachment" in response["Content-Disposition"] and response["X-Export-Truncated"] == "false"
    rows = csv_rows(response)
    assert rows[0] == COLUMNS
    assert [r[6] for r in rows[1:]] == ["SKU-1", "SKU-2", "SKU-3"]
    assert rows[1][0].endswith("+00:00") and "SECRET-COST" not in response.content.decode()  # Accra is UTC+0
    ba_rows = csv_rows(call(client_as(users["ba"]), "GET", EXPORT))
    assert {r[3] for r in ba_rows[1:]} == {"Branch A"}  # own branch only
    wa_body = call(client_as(users["wa"]), "GET", EXPORT, {"search": "alpha"}).content.decode()
    assert "TRF-9" in wa_body and "SKU-1" not in wa_body


def test_export_permissions_match_the_list(users: dict[str, Any], events: Any, locations: Any) -> None:
    assert call(client_as(users["fs"]), "GET", EXPORT).status_code == 403
    assert call(APIClient(), "GET", EXPORT).status_code in (401, 403)
    ba = client_as(users["ba"])
    assert call(ba, "GET", EXPORT, {"branch_id": locations["a"].pk}).status_code == 200
    denied = call(ba, "GET", EXPORT, {"branch_id": locations["b"].pk})
    assert denied.status_code == 403 and denied.json()["code"] == "wrong_branch"
    bad = call(client_as(users["sa"]), "GET", EXPORT, {"date_from": "yesterday"})
    assert bad.status_code == 400


def test_export_row_cap_and_formula_guard(
    users: dict[str, Any], events: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    AuditEvent.objects.create(action="=HYPERLINK(1)", target_ref="@x", actor_login_id="+1")
    sa = client_as(users["sa"])
    body = call(sa, "GET", EXPORT, {"search": "HYPERLINK"}).content.decode()
    assert "'=HYPERLINK(1)" in body and "'@x" in body and "'+1" in body
    monkeypatch.setattr(views, "EXPORT_ROW_CAP", 3)
    capped = call(sa, "GET", EXPORT)
    assert capped["X-Export-Truncated"] == "true"
    assert len(csv_rows(capped)) == 1 + 3


def test_listing_and_exporting_write_no_audit_rows(users: dict[str, Any], events: Any) -> None:
    sa = client_as(users["sa"])
    before = AuditEvent.objects.count()
    call(sa, "GET", URL)
    call(sa, "GET", EXPORT)
    assert AuditEvent.objects.count() == before


def test_audit_menu_entry_is_for_admin_roles_only() -> None:
    for role in ("super_admin", "warehouse_admin", "branch_admin"):
        assert {"key": "activity", "label": "Activity", "path": "/activity"} in home_links_for(role)
        assert len(menu_for(role)) <= 5
    assert home_links_for("front_staff") == []
    assert not any(m["key"] == "activity" for m in menu_for("front_staff"))

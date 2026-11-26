"""Branch management (B3.2, PERMISSION_TABLE rows 11-12). Super Admin only; history is kept.

Rules: `branch_type` (stored as `kind`) defaults to branch on create; only one warehouse may exist (seeded),
so a second one, or changing the type of an existing row, is refused with 400 on `branch_type`; code and name
are unique; the warehouse cannot be deactivated; deactivated branches keep every record but nothing can
act in them.
Audit events written: branch_created, branch_updated, branch_deactivated, branch_activated.
"""

from typing import Any

from django.db import IntegrityError, transaction
from django.db.models import QuerySet
from django.http import HttpRequest

from accounts.models import User
from audit.services import record_event
from branches.models import Location, LocationKind
from config.errors import ApiError
from roles import constants as c
from roles.permissions import require_action
from roles.services import active_role


def visible_locations(actor: User, is_active: bool | None = None) -> QuerySet[Location]:
    """Everyone sees active locations; only the Super Admin may see deactivated ones (row 12).

    `is_active` is the optional filter; for anyone but the Super Admin it is ignored.
    """
    if active_role(actor) != c.SUPER_ADMIN:
        return Location.objects.filter(is_active=True)
    return Location.objects.all() if is_active is None else Location.objects.filter(is_active=is_active)


def branch_filter(actor: User, branch_id: int | None) -> int | None:
    """The optional `?branch=<id>` view filter (owner, 2026-11-24). Only the Super Admin, who works across all
    branches, may use it; for roles with a fixed location the server scope applies and the value is ignored.
    """
    return branch_id if active_role(actor) == c.SUPER_ADMIN else None


def _snapshot(location: Location) -> dict[str, Any]:
    return {
        "code": location.code,
        "name": location.name,
        "branch_type": location.kind,
        "is_active": location.is_active,
    }


def _audit(request: HttpRequest, actor: User, action: str, location: Location, **values: Any) -> None:
    record_event(
        action,
        request=request,
        actor=actor,
        actor_role=active_role(actor) or "",
        location=location,
        target_type="location",
        target_ref=location.code,
        **values,
    )


def _clean(data: dict[str, Any], location: Location | None = None) -> dict[str, str]:
    """Trimmed, non-empty and unique (case-insensitive) code and name."""
    cleaned: dict[str, str] = {}
    for field in ("code", "name"):
        if field not in data:
            continue
        value = str(data[field]).strip()
        if not value:
            raise ApiError(400, "validation_error", f"Enter a {field}.", field)
        clash = Location.objects.filter(**{f"{field}__iexact": value})
        if location is not None:
            clash = clash.exclude(pk=location.pk)
        if clash.exists():
            raise ApiError(409, "conflict", f"That {field} is already in use.", field)
        cleaned[field] = value
    return cleaned


def _one_warehouse() -> ApiError:
    return ApiError(400, "validation_error", "A warehouse already exists.", "branch_type")


def create_branch(request: HttpRequest, actor: User, data: dict[str, Any]) -> Location:
    """Create a branch (row 11). Writes audit `branch_created`."""
    require_action(actor, "branches.manage")
    for field in ("code", "name"):
        if field not in data:
            raise ApiError(400, "validation_error", f"Enter a {field}.", field)
    kind = data.get("branch_type", LocationKind.BRANCH)
    if kind == LocationKind.WAREHOUSE and Location.objects.filter(kind=kind).exists():
        raise _one_warehouse()
    try:
        with transaction.atomic():
            location = Location.objects.create(kind=kind, created_by=actor, updated_by=actor, **_clean(data))
            _audit(request, actor, "branch_created", location, after=_snapshot(location))
    except IntegrityError:  # a concurrent create took the code, name or the warehouse slot first
        if kind == LocationKind.WAREHOUSE and Location.objects.filter(kind=kind).exists():
            raise _one_warehouse() from None
        raise ApiError(409, "conflict", "That code or name is already in use.") from None
    return location


def update_branch(request: HttpRequest, actor: User, location_id: int, data: dict[str, Any]) -> Location:
    """Edit code, name and/or type (row 11). Writes audit `branch_updated`.

    Type changes are refused (open question: multiple warehouses): the one warehouse is the receiving point
    and must stay, and a second one cannot exist. Sending the current type is accepted and changes nothing.
    """
    require_action(actor, "branches.manage")
    if not data.keys() & {"code", "name", "branch_type"}:
        raise ApiError(400, "validation_error", "Send a code, a name or a branch type to change.")
    try:
        with transaction.atomic():
            location = Location.objects.select_for_update().filter(pk=location_id).first()
            if location is None:
                raise ApiError(404, "not_found", "No such branch.")
            new_kind = data.get("branch_type", location.kind)
            if new_kind != location.kind:
                if new_kind == LocationKind.WAREHOUSE:
                    raise _one_warehouse()
                raise ApiError(
                    400, "validation_error", "The warehouse cannot become a branch.", "branch_type"
                )
            before = _snapshot(location)
            for field, value in _clean(data, location).items():
                setattr(location, field, value)
            location.updated_by = actor
            location.save()
            _audit(request, actor, "branch_updated", location, before=before, after=_snapshot(location))
    except IntegrityError:
        raise ApiError(409, "conflict", "That code or name is already in use.") from None
    return location


def set_branch_active(request: HttpRequest, actor: User, location_id: int, active: bool) -> Location:
    """Deactivate or activate a branch (row 11); history stays. The warehouse cannot be deactivated.

    Writes audit `branch_deactivated` or `branch_activated`.
    """
    require_action(actor, "branches.manage")
    with transaction.atomic():
        location = Location.objects.select_for_update().filter(pk=location_id).first()
        if location is None:
            raise ApiError(404, "not_found", "No such branch.")
        if not active and location.kind == LocationKind.WAREHOUSE:
            raise ApiError(409, "invalid_status_transition", "The warehouse cannot be deactivated.")
        if location.is_active == active:
            raise ApiError(
                409,
                "invalid_status_transition",
                "That branch is already active." if active else "That branch is already deactivated.",
            )
        before = _snapshot(location)
        location.is_active, location.updated_by = active, actor
        location.save()
        _audit(
            request,
            actor,
            "branch_activated" if active else "branch_deactivated",
            location,
            before=before,
            after=_snapshot(location),
        )
    return location

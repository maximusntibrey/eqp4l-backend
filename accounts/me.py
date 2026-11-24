"""Builds the contract's `Me` payload: user, active role, working branch, effective permissions, menu."""

from typing import Any

from django.http import HttpRequest

from accounts.models import User
from branches.models import Location
from roles import constants as c
from roles.menu import home_links_for, menu_for
from roles.permissions import active_grants, effective_actions, working_location_id
from roles.services import active_role, role_codes


def user_payload(user: User) -> dict[str, Any]:
    return {
        "id": user.pk,
        "login_id": user.login_id,
        "full_name": user.full_name,
        "status": user.status,
        "roles": role_codes(user),
        "permanent_location_id": user.permanent_location_id,
        "must_change_password": user.must_change_password,
        "permissions": active_grants(user),
        "last_login_at": user.last_login_at,
        "created_at": user.created_at,
    }


def working_branch(user: User, request: HttpRequest) -> Location | None:
    """BA/WA: the permanent location. FS/SA: the branch chosen this session (B3.1), if still active."""
    location_id = working_location_id(user, request.session)
    if location_id is None:
        return None
    location = Location.objects.filter(pk=location_id).first()
    if location is None or (not location.is_active and active_role(user) in (c.FRONT_STAFF, c.SUPER_ADMIN)):
        return None
    return location


def build_me(request: HttpRequest, user: User) -> dict[str, Any]:
    role = active_role(user)
    branch = working_branch(user, request)
    return {
        "user": user_payload(user),
        "active_role": role,
        "working_branch": branch,
        # Only Front Staff must choose; SA works across all branches and BA/WA have a fixed location.
        "must_pick_branch": role == c.FRONT_STAFF and branch is None,
        "all_branches": role == c.SUPER_ADMIN,
        "can_assign_multiple_roles": role == c.SUPER_ADMIN,
        "must_change_password": user.must_change_password,
        "permissions": effective_actions(user, role),
        "menu": menu_for(role),
        "home_links": home_links_for(role),
    }

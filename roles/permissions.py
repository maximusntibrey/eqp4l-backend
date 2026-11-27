"""Permission engine from docs/design/PERMISSION_TABLE.md (approved). Deny by default.

`ROLE_ACTIONS` is the table's MVP matrix reduced to the contract's ActionPermission codes.
Branch rules (section 2) are checked by `can_act_in` / `require_location`.
"""

from typing import Any

from rest_framework.permissions import BasePermission
from rest_framework.request import Request

from accounts.models import User
from accounts.permissions import IsActiveAccount, PasswordChangeNotRequired
from branches.models import Location
from config.errors import ApiError
from roles import constants as c
from roles.models import UserPermission
from roles.services import active_role

ACTIONS = [
    "users.manage",
    "users.view",
    "branches.manage",
    "branches.view",
    "working_branch.select",
    "items.view",
    "items.manage",
    "items.view_cost",
    "prices.manage",
    "stock.view",
    "stock.lookup_other_branches",
    "goods_receipts.manage",
    "dispatches.create",
    "dispatches.view",
    "dispatches.waiting",
    "dispatches.receive",
    "sales.record",  # OQ-23 (v0.1.2): menu actions for Sell, Activity, Find; Receive is dispatches.receive
    "activity.view",
    "find.use",
    "dashboard.view",  # row 40: Home dashboard (SA, WA, BA)
    "sales.cancel",  # row 39 (v0.4.2): SA, BA own branch
    "items.import",  # rows 19, 20 (v0.4.2): SA, WA
    "shortfalls.resolve",  # rows 33-35 (v0.5.0): view and resolve dispatch shortfalls, SA, WA, BA
    "design_system.view",  # row 50 (v0.7.0): frontend /design-system showcase, SA only
]

_EVERYONE = {
    "find.use",  # rows 13, 22
    "branches.view",
    "items.view",
    "stock.view",
    "stock.lookup_other_branches",
    "dispatches.view",
}
ROLE_ACTIONS: dict[str, frozenset[str]] = {
    c.SUPER_ADMIN: frozenset(a for a in ACTIONS),  # rows 4-31: every action, recorded under the SA's own ID
    c.WAREHOUSE_ADMIN: frozenset(
        _EVERYONE
        | {
            "users.view",  # warehouse only (OQ-5)
            "items.manage",
            "items.view_cost",
            "goods_receipts.manage",
            "dispatches.create",
            "activity.view",  # row 41: warehouse activity (OQ-5)
            "items.import",
            "dashboard.view",
            "shortfalls.resolve",
        }
    ),
    c.BRANCH_ADMIN: frozenset(
        _EVERYONE
        | {
            "users.view",
            "dispatches.waiting",
            "dispatches.receive",
            "sales.record",
            "sales.cancel",
            "activity.view",
            "dashboard.view",
            "shortfalls.resolve",
        }  # own branch (OQ-5)
    ),
    c.FRONT_STAFF: frozenset(_EVERYONE | {"working_branch.select", "dispatches.waiting", "sales.record"}),
}
# Per-person grants (section 3). Discount has no MVP action (Sprint 6).
GRANT_ACTIONS = {c.RECEIVE_STOCK: "dispatches.receive", c.MANAGE_PRICES: "prices.manage"}


def active_grants(user: User) -> list[str]:
    """Active per-person permission codes (revoked rows are kept but ignored)."""
    held = set(
        UserPermission.objects.filter(user=user, revoked_at__isnull=True).values_list("permission", flat=True)
    )
    return [p for p in c.PERSON_PERMISSIONS if p in held]


def effective_actions(user: User, role: str | None = None) -> list[str]:
    """Actions the user may perform in the active role, in contract order."""
    role = role or active_role(user)
    allowed = set(ROLE_ACTIONS.get(role or "", frozenset()))
    # s3: Receive stock is Front Staff only, so a stale grant on another role adds nothing
    allowed |= {
        GRANT_ACTIONS[g]
        for g in active_grants(user)
        if g in GRANT_ACTIONS and (g != c.RECEIVE_STOCK or role == c.FRONT_STAFF)
    }
    return [a for a in ACTIONS if a in allowed]


def has_action(user: Any, action: str) -> bool:
    if not (user and user.is_authenticated and user.is_active) or user.must_change_password:
        return False
    return action in effective_actions(user)


def require_action(user: Any, action: str) -> None:
    """Service-layer check for critical operations (SKILLS Authentication: permission classes plus this)."""
    if not has_action(user, action):
        raise ApiError(403, "permission_denied", "Your role is not allowed to do this.")


def action_permissions(action: str) -> list[type[BasePermission]]:
    """DRF `permission_classes` for one table action, e.g. action_permissions("items.manage").

    Keeps the project defaults (active account, no pending password change) and adds the role check,
    so a view that names an action can never be more open than the default.
    """

    class HasAction(BasePermission):
        def has_permission(self, request: Request, view: Any) -> bool:
            return has_action(request.user, action)

    HasAction.__name__ = f"HasAction[{action}]"
    return [IsActiveAccount, PasswordChangeNotRequired, HasAction]


def working_location_id(user: User, session: Any) -> int | None:
    """The active location id: BA/WA permanent location; FS and SA the one chosen in the session (B3.1)."""
    role = active_role(user)
    if role in (c.BRANCH_ADMIN, c.WAREHOUSE_ADMIN):
        return user.permanent_location_id
    chosen = session.get("working_branch_id") if session is not None else None
    return int(chosen) if chosen else None


def can_act_in(user: User, location: Location, session: Any = None) -> bool:
    """Branch rules (table s2): SA anywhere; WA/BA their own location; FS the chosen active branch."""
    if not (user.is_active and location.is_active):
        return False
    role = active_role(user)
    if role == c.SUPER_ADMIN:
        return True
    return role is not None and working_location_id(user, session) == location.id


def require_location(user: User, location: Location, session: Any = None) -> None:
    if not can_act_in(user, location, session):
        raise ApiError(403, "wrong_branch", "You cannot act in that branch.")

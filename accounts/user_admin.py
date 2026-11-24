"""User management for the Super Admin (B3.3, PERMISSION_TABLE rows 4-9).

Rules: only users.manage may write; the login ID never changes; suspend and deactivate end every session at
once (OQ-14); a reset gives a new one-time password valid 72 hours and forces a change (C5, OQ-13); only the
Super Admin grants per-person permissions and a grant never widens branch scope (s3).
Audit events written: user_created, user_updated, user_status_changed, password_reset, permission_granted,
permission_revoked. Passwords never enter an audit row.
"""

from datetime import timedelta
from typing import Any

from django.conf import settings
from django.contrib.sessions.models import Session
from django.db import transaction
from django.db.models import Q, QuerySet
from django.http import HttpRequest
from django.utils import timezone

from accounts.models import User, UserStatus
from accounts.services import _validate_location, create_user
from audit.services import record_event
from branches.models import Location
from config.errors import ApiError
from roles import constants as c
from roles.models import UserPermission
from roles.permissions import active_grants, require_action
from roles.services import active_role, replace_roles, role_codes

# (from, to) pairs the status endpoint accepts. Deactivated is final (OQ-14 "permanent"; OQ-26 to confirm).
ALLOWED_TRANSITIONS = {
    (UserStatus.ACTIVE, UserStatus.SUSPENDED),
    (UserStatus.ACTIVE, UserStatus.DEACTIVATED),
    (UserStatus.PENDING_ACTIVATION, UserStatus.SUSPENDED),
    (UserStatus.PENDING_ACTIVATION, UserStatus.DEACTIVATED),
    (UserStatus.SUSPENDED, UserStatus.ACTIVE),
    (UserStatus.SUSPENDED, UserStatus.DEACTIVATED),
}


def _working_here(location_id: int) -> list[int]:
    """Ids of users whose live session has `location_id` as working branch. shortcut: scans sessions like
    end_user_sessions; fine for a small staff, store the working branch on a table if it grows.
    shortcut: a session made before a role change keeps its stored branch until it ends (at most
    SESSION_COOKIE_AGE); only users whose active role is front_staff now are returned. Accepted."""
    ids = []
    for session in Session.objects.filter(expire_date__gt=timezone.now()).iterator():
        data = session.get_decoded()
        if data.get("working_branch_id") == location_id and data.get("_auth_user_id"):
            ids.append(int(data["_auth_user_id"]))
    return [u.pk for u in User.objects.filter(pk__in=ids) if active_role(u) == c.FRONT_STAFF]


def visible_users(actor: User) -> QuerySet[User]:
    """Table row 9 (OQ-5, OQ-26): SA all; WA the users whose permanent location is their own; BA those plus
    Front Staff currently working at their branch."""
    role = active_role(actor)
    if role == c.SUPER_ADMIN:
        return User.objects.all()
    if actor.permanent_location_id is None:
        return User.objects.none()
    scope = Q(permanent_location_id=actor.permanent_location_id)
    if role == c.BRANCH_ADMIN:
        scope |= Q(pk__in=_working_here(actor.permanent_location_id), user_roles__role__code=c.FRONT_STAFF)
    return User.objects.filter(scope).distinct()


def _lock_users(user_id: int) -> tuple[User | None, list[User]]:
    """Lock the target and every active Super Admin in ONE query, fixed pk order, before any other lock, so
    two requests that touch each other's rows queue instead of deadlocking (FIX-33). Returns the target
    (None if missing) and the locked active Super Admins."""
    active_sas = User.objects.filter(status=UserStatus.ACTIVE, user_roles__role__code=c.SUPER_ADMIN).values(
        "pk"
    )
    rows = list(
        User.objects.select_for_update(of=("self",))
        .filter(Q(pk=user_id) | Q(pk__in=active_sas))
        .order_by("pk")
    )
    return next((u for u in rows if u.pk == user_id), None), [
        u for u in rows if u.status == UserStatus.ACTIVE and c.SUPER_ADMIN in role_codes(u)
    ]


def _guard_last_super_admin(user: User, locked_sas: list[User]) -> None:
    """OQ-26: always keep one active Super Admin. `locked_sas` come from `_lock_users`."""
    if user.status != UserStatus.ACTIVE or c.SUPER_ADMIN not in role_codes(user):
        return
    if not [u for u in locked_sas if u.pk != user.pk]:
        raise ApiError(409, "conflict", "This is the last active Super Admin. Make another one first.")


def filter_users(qs: QuerySet[User], params: dict[str, Any]) -> QuerySet[User]:
    if status := params.get("status"):
        qs = qs.filter(status=status)
    if params.get("branch") is not None:  # Super Admin view filter: the user's permanent location
        qs = qs.filter(permanent_location_id=params["branch"])
    if role := params.get("role"):
        qs = qs.filter(user_roles__role__code=role)
    if q := (params.get("q") or "").strip():
        qs = qs.filter(Q(login_id__icontains=q) | Q(full_name__icontains=q))
    return qs.order_by("id")


def _audit(request: HttpRequest, actor: User, action: str, target: User, **values: Any) -> None:
    record_event(
        action,
        request=request,
        actor=actor,
        actor_role=active_role(actor) or "",
        target_type="user",
        target_ref=target.login_id,
        **values,
    )


def _snapshot(user: User) -> dict[str, Any]:
    return {
        "full_name": user.full_name,
        "roles": role_codes(user),
        "permanent_location_id": user.permanent_location_id,
        "status": user.status,
    }


def end_user_sessions(user: User) -> int:
    """Delete every session of `user`. shortcut: scans live sessions, fine for a small staff; index later."""
    ended = 0
    for session in Session.objects.filter(expire_date__gt=timezone.now()).iterator():
        if session.get_decoded().get("_auth_user_id") == str(user.pk):
            session.delete()
            ended += 1
    return ended


def one_time_password_expiry(user: User) -> Any:
    issued = user.one_time_password_issued_at or timezone.now()  # always set by create and reset
    return issued + timedelta(hours=settings.ONE_TIME_PASSWORD_HOURS)


def _location(location_id: int | None) -> Location | None:
    if location_id is None:
        return None
    location = Location.objects.filter(pk=location_id).first()
    if location is None:
        raise ApiError(400, "validation_error", "That location does not exist.", "permanent_location_id")
    return location


def create_managed_user(
    request: HttpRequest, actor: User, data: dict[str, Any], one_time_password: str
) -> User:
    """Create a user (rows 4, 6, 7). Writes audit `user_created`."""
    require_action(actor, "users.manage")
    with transaction.atomic():
        user, _ = create_user(
            full_name=data["full_name"],
            role_codes=data["roles"],
            permanent_location=_location(data.get("permanent_location_id")),
            actor=actor,
            one_time_password=one_time_password,
        )
        _audit(request, actor, "user_created", user, after=_snapshot(user))
    return user


def update_managed_user(request: HttpRequest, actor: User, user_id: int, data: dict[str, Any]) -> User:
    """Edit name, roles or permanent location (rows 4, 6, 7). The login ID is never touched.

    The result must still satisfy the role/location rule. Writes audit `user_updated`.
    """
    require_action(actor, "users.manage")
    if "login_id" in data:
        raise ApiError(400, "validation_error", "The login ID cannot be changed.", "login_id")
    with transaction.atomic():
        user, locked_sas = _lock_users(user_id)
        if user is None:
            raise ApiError(404, "not_found", "No such user.")
        before = _snapshot(user)
        codes = data.get("roles") or before["roles"]
        location = (
            _location(data["permanent_location_id"])
            if "permanent_location_id" in data
            else user.permanent_location
        )
        _validate_location(codes, location)
        if c.SUPER_ADMIN not in codes:
            _guard_last_super_admin(user, locked_sas)
        name = data.get("full_name", user.full_name).strip()
        if not name:
            raise ApiError(400, "validation_error", "Enter a full name.", "full_name")
        replace_roles(user, codes, actor)
        if c.FRONT_STAFF not in codes and c.RECEIVE_STOCK in active_grants(user):  # s3: Front Staff only
            UserPermission.objects.filter(
                user=user, permission=c.RECEIVE_STOCK, revoked_at__isnull=True
            ).update(revoked_at=timezone.now(), revoked_by=actor)
            _audit(
                request, actor, "permission_revoked", user,
                before={"permission": c.RECEIVE_STOCK}, after={"reason": "role change"},
            )  # fmt: skip
        user.full_name, user.permanent_location, user.updated_by = name, location, actor
        user.save()
        _audit(request, actor, "user_updated", user, before=before, after=_snapshot(user))
    return user


def reset_user_password(request: HttpRequest, actor: User, user_id: int, one_time_password: str) -> Any:
    """Give the user a new one-time password (row 5) and end their sessions. Returns its expiry.

    A deactivated account cannot be reset. Writes audit `password_reset` (no password in it).
    """
    require_action(actor, "users.manage")
    with transaction.atomic():
        user = User.objects.select_for_update().filter(pk=user_id).first()
        if user is None:
            raise ApiError(404, "not_found", "No such user.")
        if user.status == UserStatus.DEACTIVATED:
            raise ApiError(409, "invalid_status_transition", "A deactivated account cannot be reset.")
        user.set_password(one_time_password)
        user.must_change_password = True
        user.one_time_password_issued_at = timezone.now()
        user.updated_by = actor
        user.save()
        end_user_sessions(user)
        expires = one_time_password_expiry(user)
        _audit(request, actor, "password_reset", user, after={"expires_at": expires.isoformat()})
    return expires


def set_user_status(request: HttpRequest, actor: User, user_id: int, target: str, reason: str = "") -> User:
    """Activate, suspend or deactivate (row 4, OQ-14). Suspend and deactivate end all sessions.

    SA cannot change their own status. Writes audit `user_status_changed`.
    """
    require_action(actor, "users.manage")
    with transaction.atomic():
        user, locked_sas = _lock_users(user_id)
        if user is None:
            raise ApiError(404, "not_found", "No such user.")
        if target != UserStatus.ACTIVE:
            # before the own-status check: the clearer message for the last SA
            _guard_last_super_admin(user, locked_sas)
        if user.pk == actor.pk:
            raise ApiError(409, "conflict", "You cannot change your own status.", "status")
        if (user.status, target) not in ALLOWED_TRANSITIONS:
            raise ApiError(
                409, "invalid_status_transition", f"A {user.status} account cannot become {target}.", "status"
            )
        before = user.status
        # Back to active: an account that never changed its one-time password stays pending (OQ-22).
        user.status = (
            UserStatus.PENDING_ACTIVATION
            if target == UserStatus.ACTIVE and user.must_change_password
            else target
        )
        user.updated_by = actor
        user.save()
        ended = end_user_sessions(user) if target != UserStatus.ACTIVE else 0
        _audit(
            request,
            actor,
            "user_status_changed",
            user,
            before={"status": before},
            after={"status": user.status, "reason": reason, "sessions_ended": ended},
        )
    return user


def set_person_permissions(request: HttpRequest, actor: User, user_id: int, codes: list[str]) -> list[str]:
    """Set the full list of per-person permissions (row 8, s3). Writes one audit event per grant or revoke.

    Receive stock can only be held by Front Staff (s3). A grant never changes branch scope.
    """
    require_action(actor, "users.manage")
    wanted = set(codes)
    with transaction.atomic():
        user = User.objects.select_for_update().filter(pk=user_id).first()
        if user is None:
            raise ApiError(404, "not_found", "No such user.")
        if c.RECEIVE_STOCK in wanted and c.FRONT_STAFF not in role_codes(user):
            raise ApiError(400, "validation_error", "Only Front Staff can hold Receive stock.", "permissions")
        held = set(active_grants(user))
        now = timezone.now()
        for code in sorted(wanted - held):
            UserPermission.objects.create(user=user, permission=code, granted_by=actor)
            _audit(request, actor, "permission_granted", user, after={"permission": code})
        for code in sorted(held - wanted):
            UserPermission.objects.filter(user=user, permission=code, revoked_at__isnull=True).update(
                revoked_at=now, revoked_by=actor
            )
            _audit(request, actor, "permission_revoked", user, before={"permission": code})
        return active_grants(user)

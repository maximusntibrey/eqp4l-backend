"""Accounts: login ID generator, user creation, login/logout and password change (B2.2, B2.3).

Rules enforced here: IDs are generated under a row lock, never changed, never reused (ERD s4);
5 failed logins per login ID and IP per 15 minutes lock that pair for 15 minutes (OQ-13);
a one-time password is valid 72 hours and forces a change at first login (C5, OQ-13, OQ-22).
Audit events written: login_success, login_failed, logout, password_changed.
"""

import math
import secrets
from collections.abc import Callable
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.contrib.auth import login as django_login
from django.contrib.auth import logout as django_logout
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.hashers import check_password, make_password
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import connection, transaction
from django.db.models import Max, Q
from django.http import HttpRequest
from django.utils import timezone

from accounts.models import LoginEvent, LoginIdSequence, LoginLog, User, UserStatus
from audit.services import client_meta, record_event
from branches.models import Location, LocationKind
from config.errors import ApiError
from roles import constants as c
from roles.permissions import require_action
from roles.services import active_role, assign_roles

WRONG_CURRENT = "wrong_current_password"  # failure_reason of a refused password change (own rate limit)
_dummy_hash: list[str] = []  # computed once; lets an unknown login ID cost the same time as a wrong password


def normalise_login_id(raw: str) -> str:
    return raw.strip().upper()[:64]


def next_login_id(prefix: str) -> str:
    """Issue the next ID for `prefix` ("SA" or "USR") under a row lock. The counter only increases."""
    with transaction.atomic():
        seq = LoginIdSequence.objects.select_for_update().get(prefix=prefix)
        seq.last_number += 1
        seq.save(update_fields=["last_number"])
    return f"{prefix}-{seq.last_number:04d}"


def generate_one_time_password() -> str:
    return secrets.token_urlsafe(9)  # 12 characters, shown once to the Super Admin


def _validate_location(codes: list[str], location: Location | None) -> None:
    """BA needs a branch, WA the warehouse; SA and FS have none (contract UserCreate)."""
    field = "permanent_location_id"
    needs_branch, needs_warehouse = c.BRANCH_ADMIN in codes, c.WAREHOUSE_ADMIN in codes
    if needs_branch and needs_warehouse:
        # OQ-23: one permanent location cannot be both a branch and the warehouse.
        raise ApiError(
            400, "validation_error", "Warehouse Admin and Branch Admin cannot be combined.", "roles"
        )
    if not (needs_branch or needs_warehouse):
        if location is not None:
            raise ApiError(400, "validation_error", "This role has no permanent location.", field)
        return
    if location is None:
        raise ApiError(400, "validation_error", "A permanent location is required for this role.", field)
    wanted = LocationKind.WAREHOUSE if needs_warehouse else LocationKind.BRANCH
    if location.kind != wanted or not location.is_active:
        raise ApiError(400, "validation_error", f"Choose an active {wanted.value}.", field)


def create_user(
    *,
    full_name: str,
    role_codes: list[str],
    permanent_location: Location | None = None,
    actor: User | None = None,
    one_time_password: str | None = None,
) -> tuple[User, str]:
    """Create an account with a generated login ID and a one-time password (returned, never stored plain).

    Rule: only users.manage (Super Admin) may create; `actor=None` is the internal bootstrap path (seed).
    The ID is SA-#### when the account holds the Super Admin role, otherwise USR-####. Status starts as
    pending_activation with must_change_password set (OQ-22). The caller writes the audit event.
    """
    if actor is not None:
        require_action(actor, "users.manage")
    name = full_name.strip()
    if not name or len(name) > 150:
        raise ApiError(400, "validation_error", "Enter a full name of up to 150 characters.", "full_name")
    codes = list(dict.fromkeys(role_codes))
    _validate_location(codes, permanent_location)
    one_time = one_time_password or generate_one_time_password()
    with transaction.atomic():
        user = User(
            login_id=next_login_id("SA" if c.SUPER_ADMIN in codes else "USR"),
            full_name=name,
            status=UserStatus.PENDING_ACTIVATION,
            must_change_password=True,
            one_time_password_issued_at=timezone.now(),
            permanent_location=permanent_location,
            created_by=actor,
            updated_by=actor,
        )
        user.set_password(one_time)
        user.save()
        assign_roles(user, codes, actor)
    return user, one_time


# ---- login -----------------------------------------------------------------------------------


def lockout_seconds(login_id: str, ip: str | None, now: Any = None, *, password_change: bool = False) -> int:
    """Seconds left of the wait; 0 when they may try.

    Login: counted per login ID and IP. Password change: counted per user (any IP), wrong-current tries only.
    """
    now = now or timezone.now()
    window = timedelta(minutes=settings.LOGIN_WINDOW_MINUTES)
    base = LoginLog.objects.filter(login_id_attempted=login_id)
    if password_change:
        base = base.filter(Q(event=LoginEvent.SUCCESS) | Q(failure_reason=WRONG_CURRENT))
    else:
        base = base.filter(ip=ip).exclude(failure_reason=WRONG_CURRENT)
    last_ok = base.filter(event=LoginEvent.SUCCESS).aggregate(m=Max("at"))["m"]
    start = max(now - window, last_ok) if last_ok else now - window
    failures = list(
        base.filter(event=LoginEvent.FAILED, at__gt=start)
        .exclude(failure_reason="rate_limited")  # blocked attempts must not extend the wait
        .order_by("-at")
        .values_list("at", flat=True)[: settings.LOGIN_MAX_FAILURES]
    )
    if len(failures) < settings.LOGIN_MAX_FAILURES:
        return 0
    return max(0, math.ceil((failures[0] + window - now).total_seconds()))


def _log_login(
    request: HttpRequest,
    event: str,
    login_id: str,
    user: User | None,
    reason: str = "",
    audit_action: str | None = None,
) -> None:
    """One login_log row and one audit event, together. No passwords are ever logged."""
    meta = client_meta(request)
    with transaction.atomic():
        LoginLog.objects.create(
            login_id_attempted=login_id, user=user, event=event, failure_reason=reason, **meta
        )
        record_event(
            audit_action or event,
            request=request,
            actor=user,
            actor_login_id=login_id,
            actor_role=(active_role(user) or "") if user else "",
            target_type="user",
            target_ref=user.login_id if user else login_id,
            after={"reason": reason} if reason else None,
        )


def _refuse(request: HttpRequest, login_id: str, user: User | None, reason: str, error: ApiError) -> ApiError:
    _log_login(request, LoginEvent.FAILED, login_id, user, reason)
    return error


def check_password_or_dummy(user: User | None, password: str) -> bool:
    if user is None:
        if not _dummy_hash:
            _dummy_hash.append(make_password("not-a-real-password"))
        check_password(password, _dummy_hash[0])
        return False
    return user.check_password(password)


def _serialised[T](key: str, work: Callable[[], T]) -> T:
    """Run `work` under a per-key advisory lock so count-then-log cannot race (held to transaction end).

    An ApiError raised by `work` is re-raised after the commit so its failure rows stay.
    """
    error: ApiError | None = None
    with transaction.atomic():
        with connection.cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", [key])
        try:
            return work()
        except ApiError as exc:
            error = exc
    raise error


def _rate_limited(wait: int) -> ApiError:
    return ApiError(
        429,
        "rate_limited",
        f"Too many failed attempts. Try again in {math.ceil(wait / 60)} minute(s).",
        headers={"Retry-After": str(wait)},
    )


def authenticate_login(request: HttpRequest, raw_login_id: str, password: str) -> User:
    """Check credentials and account state; log every failure. Returns the user to log in."""
    login_id = normalise_login_id(raw_login_id)
    ip = client_meta(request)["ip"]
    return _serialised(f"login:{login_id}:{ip}", lambda: _authenticate(request, login_id, ip, password))


def _authenticate(request: HttpRequest, login_id: str, ip: str | None, password: str) -> User:
    wait = lockout_seconds(login_id, ip)
    if wait:
        _log_login(request, LoginEvent.FAILED, login_id, None, "rate_limited")
        raise _rate_limited(wait)
    user = User.objects.filter(login_id=login_id).first()
    if not check_password_or_dummy(user, password) or user is None:
        raise _refuse(
            request,
            login_id,
            user,
            "invalid_credentials",
            ApiError(401, "invalid_credentials", "Login ID or password is wrong."),
        )
    if not user.is_active:
        raise _refuse(
            request,
            login_id,
            user,
            "account_inactive",
            ApiError(403, "account_inactive", "This account is not active. Contact a Super Admin."),
        )
    issued = user.one_time_password_issued_at
    if (
        user.must_change_password
        and issued
        and timezone.now() - issued > timedelta(hours=settings.ONE_TIME_PASSWORD_HOURS)
    ):
        raise _refuse(
            request,
            login_id,
            user,
            "one_time_password_expired",
            ApiError(
                401,
                "invalid_credentials",
                "This one-time password has expired. Ask a Super Admin for a new one.",
            ),
        )
    return user


def complete_login(request: HttpRequest, user: User) -> None:
    """Start the session (new key, new CSRF token), stamp last login, log success."""
    django_login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    User.objects.filter(pk=user.pk).update(last_login_at=timezone.now())
    user.refresh_from_db(fields=["last_login_at"])
    _log_login(request, LoginEvent.SUCCESS, user.login_id, user)


def end_session(request: HttpRequest, user: User) -> None:
    _log_login(request, LoginEvent.LOGOUT, user.login_id, user)
    django_logout(request)


# ---- password change -------------------------------------------------------------------------


def _check_current_password(request: HttpRequest, user: User, current_password: str) -> None:
    """Wrong current password: 5 per 15 minutes per user, then 429. Tries are logged, never the password."""
    wait = lockout_seconds(user.login_id, None, password_change=True)
    if wait:
        _log_login(request, LoginEvent.FAILED, user.login_id, user, "rate_limited", "password_change_failed")
        raise _rate_limited(wait)
    if not user.check_password(current_password):
        _log_login(request, LoginEvent.FAILED, user.login_id, user, WRONG_CURRENT, "password_change_failed")
        raise ApiError(400, "validation_error", "Current password is wrong.", "current_password")


def change_password(request: HttpRequest, user: User, current_password: str, new_password: str) -> None:
    """Change the user's own password. Clears the forced change; pending_activation becomes active (OQ-22).

    Writes audit event `password_changed`. Other sessions of the user end (session hash changes).
    """
    _serialised(f"password:{user.login_id}", lambda: _check_current_password(request, user, current_password))
    try:
        validate_password(new_password, user)
    except DjangoValidationError as exc:
        raise ApiError(400, "validation_error", exc.messages[0], "new_password") from exc
    if user.check_password(new_password):
        raise ApiError(
            400, "validation_error", "The new password must differ from the old one.", "new_password"
        )
    forced = user.must_change_password
    with transaction.atomic():
        user.set_password(new_password)
        user.must_change_password = False
        user.one_time_password_issued_at = None
        if user.status == UserStatus.PENDING_ACTIVATION:
            user.status = UserStatus.ACTIVE
        user.updated_by = user
        user.save()
        record_event(
            "password_changed",
            request=request,
            actor=user,
            actor_role=active_role(user) or "",
            target_type="user",
            target_ref=user.login_id,
            after={"forced_change": forced},
        )
    update_session_auth_hash(request, user)

"""The audit service: the only writer of audit events. Rows are append-only."""

import uuid
from typing import Any

from django.http import HttpRequest

from accounts.models import User
from audit.models import AuditEvent
from branches.models import Location


def client_meta(request: HttpRequest | None) -> dict[str, Any]:
    """IP and device of the request. REMOTE_ADDR only: behind a proxy the host must set it."""
    if request is None:
        return {"ip": None, "user_agent": ""}
    return {
        "ip": request.META.get("REMOTE_ADDR") or None,
        "user_agent": request.META.get("HTTP_USER_AGENT", "")[:500],
    }


def record_event(
    action: str,
    *,
    request: HttpRequest | None = None,
    actor: User | None = None,
    actor_login_id: str = "",
    actor_role: str = "",
    location: Location | None = None,
    target_type: str = "",
    target_ref: str = "",
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    is_self_approval: bool = False,
    operation_id: uuid.UUID | None = None,
) -> AuditEvent:
    """Write one audit event. Never pass passwords or tokens in before/after."""
    return AuditEvent.objects.create(
        actor=actor,
        actor_login_id=actor_login_id or (actor.login_id if actor else ""),
        actor_role=actor_role,
        location=location,
        action=action,
        target_type=target_type,
        target_ref=target_ref,
        before_values=before,
        after_values=after,
        is_self_approval=is_self_approval,
        operation_id=operation_id,
        **client_meta(request),
    )

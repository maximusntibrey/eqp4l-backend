"""Working-branch selection and switching (B3.1, PERMISSION_TABLE row 10, OQ-12).

Rules: Front Staff may pick any active branch, Super Admin an optional context branch; Branch Admin and
Warehouse Admin have a fixed location and are refused. The choice lives in the server session, so the client
can never name its own scope. Every switch writes one switch-log row and one audit event together
(`working_branch_switched`). Choosing the branch already in use is not a switch and writes nothing.
"""

from django.db import transaction
from django.http import HttpRequest

from accounts.models import User
from audit.services import record_event
from branch_access.models import SwitchLog
from branches.models import Location, LocationKind
from config.errors import ApiError
from roles.permissions import require_action
from roles.services import active_role

SESSION_KEY = "working_branch_id"  # read by roles.permissions.working_location_id


def set_working_branch(request: HttpRequest, actor: User, branch_id: int) -> bool:
    """Choose or switch the working branch. Returns True when it was a switch (and was logged)."""
    require_action(actor, "working_branch.select")
    target = Location.objects.filter(pk=branch_id, kind=LocationKind.BRANCH, is_active=True).first()
    if target is None:
        raise ApiError(400, "validation_error", "Choose an active branch.", "branch_id")
    current = request.session.get(SESSION_KEY)
    if current == target.pk:
        return False
    with transaction.atomic():
        previous = Location.objects.filter(pk=current).first() if current else None
        SwitchLog.objects.create(user=actor, from_location=previous, to_location=target)
        record_event(
            "working_branch_switched",
            request=request,
            actor=actor,
            actor_role=active_role(actor) or "",
            location=target,
            target_type="location",
            target_ref=target.code,
            before={"location_id": previous.pk if previous else None},
            after={"location_id": target.pk},
        )
        request.session[SESSION_KEY] = target.pk
    return True

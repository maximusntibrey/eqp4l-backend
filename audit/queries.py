"""Activity log reads (B7.2, PERMISSION_TABLE rows 41 and 45): SA all, WA the warehouse, BA the own branch.

Events without a location (user administration, logins) are visible to the Super Admin only. Only
metadata is returned; the stored before/after values (which may hold other fields) are never read here.
"""

from django.db.models import QuerySet

from accounts.models import User
from audit.models import AuditEvent
from config.errors import ApiError
from roles import constants as c
from roles.permissions import working_location_id
from roles.services import active_role


def scoped_events(user: User, session: object, branch_id: int | None = None) -> QuerySet[AuditEvent]:
    qs = AuditEvent.objects.select_related("location").order_by("-occurred_at", "-id")
    if active_role(user) == c.SUPER_ADMIN:
        return qs.filter(location_id=branch_id) if branch_id else qs
    own = working_location_id(user, session)
    if own is None:
        return qs.none()
    if branch_id is not None and branch_id != own:
        raise ApiError(403, "wrong_branch", "You can only see your own location's activity.")
    return qs.filter(location_id=own)

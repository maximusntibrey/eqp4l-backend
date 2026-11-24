"""Role lookups and role assignment (B2.4: only Super Admins may assign more than one role)."""

from collections.abc import Iterable

from django.contrib.auth.models import AnonymousUser
from django.db import transaction

from accounts.models import User
from config.errors import ApiError
from roles.constants import ROLE_PRIORITY, SUPER_ADMIN
from roles.models import Role, UserRole


def role_codes(user: User) -> list[str]:
    """The user's role codes, highest authority first."""
    held = set(UserRole.objects.filter(user=user).values_list("role__code", flat=True))
    return [code for code in ROLE_PRIORITY if code in held]


def active_role(user: User) -> str | None:
    """The role in use. Until role switching (Sprint 5) it is the user's first role by priority."""
    codes = role_codes(user)
    return codes[0] if codes else None


def is_super_admin(user: User | AnonymousUser | None) -> bool:
    return bool(user and user.is_authenticated and SUPER_ADMIN in role_codes(user))


def assign_roles(user: User, codes: Iterable[str], actor: User | None) -> None:
    """Give `user` the roles in `codes`. More than one role needs a Super Admin actor (BE s2).

    `actor=None` is the internal bootstrap path (seed) and may only assign a single role.
    Writes no audit row itself: the caller (user management, B3.3) records the audit event.
    """
    wanted = list(dict.fromkeys(codes))
    if not wanted:
        raise ApiError(400, "validation_error", "Choose at least one role.", "roles")
    unknown = [c for c in wanted if c not in ROLE_PRIORITY]
    if unknown:
        raise ApiError(400, "validation_error", f"Unknown role: {unknown[0]}.", "roles")
    if actor is not None:
        from roles.permissions import require_action  # local: roles.permissions imports this module

        require_action(actor, "users.manage")
    if len(set(wanted) | set(role_codes(user))) > 1 and not is_super_admin(actor):
        raise ApiError(
            403, "permission_denied", "Only a Super Admin can give a user more than one role.", "roles"
        )
    roles = {r.code: r for r in Role.objects.filter(code__in=wanted)}
    for code in wanted:
        UserRole.objects.get_or_create(user=user, role=roles[code], defaults={"assigned_by": actor})


def replace_roles(user: User, codes: Iterable[str], actor: User) -> None:
    """Make `codes` the user's whole role set (B3.3). Super Admin only; the caller writes the audit event."""
    wanted = list(dict.fromkeys(codes))
    with transaction.atomic():
        UserRole.objects.filter(user=user).exclude(role__code__in=wanted).delete()
        assign_roles(user, wanted, actor)

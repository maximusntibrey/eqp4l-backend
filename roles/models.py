from django.conf import settings
from django.db import models

from roles.constants import PERSON_PERMISSIONS


class Role(models.Model):
    """Four fixed roles, seeded by post_migrate in config/reference_data.py."""

    code = models.CharField(max_length=30, unique=True)
    name = models.CharField(max_length=50)

    def __str__(self) -> str:
        return self.code


class UserRole(models.Model):
    """Join table now so Sprint 5 multi-role needs no migration."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="user_roles")
    role = models.ForeignKey(Role, on_delete=models.PROTECT, related_name="user_roles")
    assigned_at = models.DateTimeField(auto_now_add=True)
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "role"], name="user_roles_unique")]


class UserPermission(models.Model):
    """Per-person grants; a revoke keeps the row (revoked_at set)."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="grants")
    permission = models.CharField(max_length=30)
    granted_at = models.DateTimeField(auto_now_add=True)
    granted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(permission__in=PERSON_PERMISSIONS), name="user_permissions_code_valid"
            ),
            # One active grant per person and permission.
            models.UniqueConstraint(
                fields=["user", "permission"],
                condition=models.Q(revoked_at__isnull=True),
                name="user_permissions_one_active",
            ),
        ]

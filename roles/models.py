"""Roles, role assignments and per-person permission grants (ERD s3.2)."""

from django.conf import settings
from django.db import models
from django.db.models import Q


class RoleCode(models.TextChoices):
    SUPER_ADMIN = "super_admin"
    WAREHOUSE_ADMIN = "warehouse_admin"
    BRANCH_ADMIN = "branch_admin"
    FRONT_STAFF = "front_staff"


class PermissionCode(models.TextChoices):
    RECEIVE_STOCK = "receive_stock"
    MANAGE_PRICES = "manage_prices"
    APPLY_DISCOUNT = "apply_discount"


def _revoked_pair_consistent() -> Q:
    """``(revoked_at IS NULL) = (revoked_by IS NULL)``."""
    return Q(revoked_at__isnull=True, revoked_by__isnull=True) | Q(
        revoked_at__isnull=False, revoked_by__isnull=False
    )


class Role(models.Model):
    """Seeded by migration: four rows."""

    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=50)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(code__in=[c.value for c in RoleCode]), name="roles_role_code_valid"
            ),
        ]

    def __str__(self) -> str:
        return self.code


class UserRole(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="user_roles"
    )
    role = models.ForeignKey(Role, on_delete=models.PROTECT, related_name="user_roles")
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    assigned_at = models.DateTimeField()
    revoked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=_revoked_pair_consistent(), name="roles_userrole_revoked_pair"
            ),
            models.UniqueConstraint(
                fields=["user", "role"],
                condition=Q(revoked_at__isnull=True),
                name="roles_userrole_one_active",
            ),
        ]


class UserPermissionGrant(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="permission_grants"
    )
    permission = models.CharField(max_length=20, choices=PermissionCode.choices)
    granted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    granted_at = models.DateTimeField()
    revoked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(permission__in=[p.value for p in PermissionCode]),
                name="roles_grant_permission_valid",
            ),
            models.CheckConstraint(
                condition=_revoked_pair_consistent(), name="roles_grant_revoked_pair"
            ),
            models.UniqueConstraint(
                fields=["user", "permission"],
                condition=Q(revoked_at__isnull=True),
                name="roles_grant_one_active",
            ),
        ]

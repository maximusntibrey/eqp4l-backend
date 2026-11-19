"""Locations: the central warehouse and the branches (ERD s3.3)."""

from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower

from eqp4l.db import AuditFields


class BranchKind(models.TextChoices):
    WAREHOUSE = "warehouse"
    BRANCH = "branch"


class BranchStatus(models.TextChoices):
    ACTIVE = "active"
    INACTIVE = "inactive"


class Branch(AuditFields):
    code = models.CharField(max_length=10, unique=True)
    name = models.CharField(max_length=100)
    kind = models.CharField(max_length=10, choices=BranchKind.choices)
    location = models.CharField(max_length=200, blank=True, default="")
    contact = models.CharField(max_length=100, blank=True, default="")
    status = models.CharField(max_length=10, choices=BranchStatus.choices)

    class Meta:
        verbose_name_plural = "branches"
        constraints = [
            models.UniqueConstraint(Lower("name"), name="branches_branch_name_ci_uniq"),
            models.CheckConstraint(
                condition=Q(kind__in=[k.value for k in BranchKind]),
                name="branches_branch_kind_valid",
            ),
            # Exactly one central warehouse (E1).
            models.UniqueConstraint(
                fields=["kind"],
                condition=Q(kind="warehouse"),
                name="branches_branch_one_warehouse",
            ),
            models.CheckConstraint(
                condition=Q(status__in=[s.value for s in BranchStatus]),
                name="branches_branch_status_valid",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.code} {self.name}"

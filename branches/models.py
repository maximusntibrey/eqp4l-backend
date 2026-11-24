from django.conf import settings
from django.db import models

from config.dbutils import choice_check


class LocationKind(models.TextChoices):
    WAREHOUSE = "warehouse"
    BRANCH = "branch"


class Location(models.Model):
    """The central warehouse and the branches in one table, so balances, dispatches and ledger share a key."""

    kind = models.CharField(max_length=10, choices=LocationKind.choices)
    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=100, unique=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )

    class Meta:
        constraints = [
            choice_check("kind", LocationKind, "locations_kind_valid"),
            # Single location rule (ERD s4): only one warehouse row.
            models.UniqueConstraint(
                fields=["kind"], condition=models.Q(kind="warehouse"), name="locations_one_warehouse"
            ),
        ]

    def __str__(self) -> str:
        return self.name

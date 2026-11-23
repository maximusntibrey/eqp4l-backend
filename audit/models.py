from django.conf import settings
from django.db import models
from django.utils import timezone

from config.append_only import AppendOnlyModel


class AuditEvent(AppendOnlyModel):
    """Append-only audit trail. The action list is open-ended."""

    occurred_at = models.DateTimeField(default=timezone.now)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT, related_name="+")
    actor_login_id = models.CharField(max_length=64, blank=True)  # copy, survives anything
    actor_role = models.CharField(max_length=30, blank=True)
    location = models.ForeignKey(
        "branches.Location", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    action = models.CharField(max_length=60)
    target_type = models.CharField(max_length=40, blank=True)
    target_ref = models.CharField(max_length=60, blank=True)
    before_values = models.JSONField(null=True, blank=True)
    after_values = models.JSONField(null=True, blank=True)
    is_self_approval = models.BooleanField(default=False)
    ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    operation_id = models.UUIDField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["occurred_at"], name="audit_occurred_idx"),
            models.Index(fields=["actor", "occurred_at"], name="audit_actor_idx"),
        ]

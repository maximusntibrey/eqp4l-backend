"""The append-only audit log (ERD s3.9, s7). Rows are inserted only by the audit service."""

from django.conf import settings
from django.db import models
from django.utils import timezone

from eqp4l.append_only import AppendOnlyModel


class AuditEvent(AppendOnlyModel):
    occurred_at = models.DateTimeField(default=timezone.now)
    # Null only for failed logins of unknown IDs.
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    actor_login_id = models.CharField(max_length=12, blank=True, default="")
    role_used = models.CharField(max_length=20, blank=True, default="")
    branch = models.ForeignKey(
        "branches.Branch", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    # An open string with documented known codes (OQ-23), so no CHECK on the value.
    action = models.CharField(max_length=60)
    reference_type = models.CharField(max_length=30, blank=True, default="")
    reference_id = models.BigIntegerField(null=True, blank=True)
    previous_value = models.JSONField(null=True, blank=True)
    new_value = models.JSONField(null=True, blank=True)
    self_approved = models.BooleanField(default=False, db_default=False)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=300, blank=True, default="")
    request_id = models.UUIDField(null=True, blank=True)
    operation = models.ForeignKey(
        "stock_ledger.Operation",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="audit_events",
    )

    class Meta:
        indexes = [
            models.Index(fields=["-occurred_at"], name="audit_event_occurred_idx"),
            models.Index(fields=["actor", "occurred_at"], name="audit_event_actor_idx"),
            models.Index(fields=["branch", "occurred_at"], name="audit_event_branch_idx"),
            models.Index(fields=["action", "occurred_at"], name="audit_event_action_idx"),
            models.Index(fields=["reference_type", "reference_id"], name="audit_event_ref_idx"),
        ]

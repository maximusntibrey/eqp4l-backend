import uuid

from django.conf import settings
from django.db import models
from django.db.models.functions import Length, Trim
from django.db.models.lookups import GreaterThan
from django.utils import timezone

from config.append_only import AppendOnlyModel
from config.dbutils import choice_check


class DispatchStatus(models.TextChoices):
    IN_TRANSIT = "in_transit"
    COMPLETED = "completed"
    PARTIALLY_RECEIVED = "partially_received"
    REJECTED = "rejected"


class Dispatch(models.Model):
    reference = models.CharField(max_length=20, unique=True)  # TRF-000001
    origin_location = models.ForeignKey("branches.Location", on_delete=models.PROTECT, related_name="+")
    destination_location = models.ForeignKey("branches.Location", on_delete=models.PROTECT, related_name="+")
    status = models.CharField(
        max_length=20, choices=DispatchStatus.choices, default=DispatchStatus.IN_TRANSIT
    )
    dispatched_at = models.DateTimeField(default=timezone.now)
    dispatched_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    received_at = models.DateTimeField(null=True, blank=True)
    received_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    receive_note = models.TextField(blank=True)
    operation_id = models.UUIDField(unique=True, default=uuid.uuid4)

    class Meta:
        constraints = [
            choice_check("status", DispatchStatus, "dispatches_status_valid"),
            models.CheckConstraint(
                condition=~models.Q(origin_location=models.F("destination_location")),
                name="dispatches_origin_differs",
            ),
        ]


class DispatchLine(models.Model):
    dispatch = models.ForeignKey(Dispatch, on_delete=models.PROTECT, related_name="lines")
    item = models.ForeignKey("inventory.Item", on_delete=models.PROTECT, related_name="+")
    qty_sent = models.IntegerField()
    qty_received = models.IntegerField(null=True, blank=True)  # physical count, null until received
    qty_accepted = models.IntegerField(null=True, blank=True)  # credited to destination
    qty_rejected = models.IntegerField(null=True, blank=True)
    line_note = models.TextField(blank=True)  # required if accepted < sent (service rule)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["dispatch", "item"], name="dispatch_lines_item_once"),
            models.CheckConstraint(condition=models.Q(qty_sent__gt=0), name="dispatch_lines_sent_positive"),
            models.CheckConstraint(
                condition=models.Q(qty_received__isnull=True)
                | (models.Q(qty_received__gte=0) & models.Q(qty_received__lte=models.F("qty_sent"))),
                name="dispatch_lines_received_within_sent",
            ),
            models.CheckConstraint(
                condition=models.Q(qty_accepted__isnull=True) | models.Q(qty_accepted__gte=0),
                name="dispatch_lines_accepted_non_negative",
            ),
            models.CheckConstraint(
                condition=models.Q(qty_rejected__isnull=True) | models.Q(qty_rejected__gte=0),
                name="dispatch_lines_rejected_non_negative",
            ),
            models.CheckConstraint(
                condition=models.Q(qty_accepted__isnull=True)
                | models.Q(qty_rejected__isnull=True)
                | models.Q(qty_received__isnull=True)
                | models.Q(qty_received__gte=models.F("qty_accepted") + models.F("qty_rejected")),
                name="dispatch_lines_accepted_rejected_within_received",
            ),
        ]


class ResolutionAction(models.TextChoices):
    RETURN_TO_SENDER = "return_to_sender"
    CONFIRM_LOSS = "confirm_loss"
    RECORD_DAMAGE = "record_damage"


class DispatchResolution(AppendOnlyModel):
    """One row per shortfall resolution; append-only; the note is mandatory."""

    reference = models.CharField(max_length=20, unique=True)  # RES-000001
    dispatch_line = models.ForeignKey(DispatchLine, on_delete=models.PROTECT, related_name="resolutions")
    action = models.CharField(max_length=20, choices=ResolutionAction.choices)
    quantity = models.IntegerField()
    note = models.TextField()
    resolved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    resolved_role = models.CharField(max_length=30)
    resolved_at = models.DateTimeField(default=timezone.now)
    is_self_approval = models.BooleanField(default=False)
    operation_id = models.UUIDField(unique=True, default=uuid.uuid4)

    class Meta:
        constraints = [
            choice_check("action", ResolutionAction, "resolutions_action_valid"),
            models.CheckConstraint(condition=models.Q(quantity__gt=0), name="resolutions_qty_positive"),
            models.CheckConstraint(
                condition=GreaterThan(Length(Trim("note")), 0), name="resolutions_note_not_blank"
            ),
        ]

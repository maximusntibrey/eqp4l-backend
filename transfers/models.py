"""Dispatches, their lines, discrepancies and resolutions (ERD s3.6, s6)."""

from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import CharField, DecimalField, F, Q, Value
from django.db.models.functions import Cast, Coalesce, Concat, Length, LPad, Trim
from django.db.models.lookups import GreaterThan

_ZERO = Value(Decimal("0"), output_field=DecimalField(max_digits=12, decimal_places=3))


class DispatchKind(models.TextChoices):
    WAREHOUSE_DISPATCH = "warehouse_dispatch"


class DispatchStatus(models.TextChoices):
    IN_TRANSIT = "in_transit"
    PARTIALLY_RECEIVED = "partially_received"
    COMPLETED = "completed"
    REJECTED = "rejected"
    UNDER_INVESTIGATION = "under_investigation"


class LineStatus(models.TextChoices):
    IN_TRANSIT = "in_transit"
    RECEIVED = "received"
    UNDER_INVESTIGATION = "under_investigation"
    RESOLVED_RETURNED = "resolved_returned"
    RESOLVED_LOST = "resolved_lost"
    RESOLVED_DAMAGED = "resolved_damaged"
    RESOLVED_MIXED = "resolved_mixed"


class DiscrepancyStatus(models.TextChoices):
    OPEN = "open"
    RESOLVED = "resolved"


class ResolutionOutcome(models.TextChoices):
    RETURN = "return"
    LOSS = "loss"
    DAMAGE = "damage"


class Dispatch(models.Model):
    reference = models.GeneratedField(
        expression=Concat(Value("DSP-"), LPad(Cast("id", CharField()), 6, Value("0"))),
        output_field=CharField(max_length=20),
        db_persist=True,
        unique=True,
    )
    kind = models.CharField(
        max_length=20, choices=DispatchKind.choices, default=DispatchKind.WAREHOUSE_DISPATCH
    )
    origin = models.ForeignKey(
        "branches.Branch", on_delete=models.PROTECT, related_name="dispatches_out"
    )
    destination = models.ForeignKey(
        "branches.Branch", on_delete=models.PROTECT, related_name="dispatches_in"
    )
    status = models.CharField(max_length=24, choices=DispatchStatus.choices)
    reason = models.CharField(max_length=200, null=True, blank=True)  # noqa: DJ001 - ERD: null
    dispatched_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    dispatched_at = models.DateTimeField()
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    decision_note = models.TextField(blank=True, default="")
    operation = models.OneToOneField(
        "stock_ledger.Operation", on_delete=models.PROTECT, related_name="dispatch"
    )
    receive_operation = models.OneToOneField(
        "stock_ledger.Operation",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="received_dispatch",
    )

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(kind__in=[k.value for k in DispatchKind]),
                name="transfers_dispatch_kind_valid",
            ),
            models.CheckConstraint(
                condition=~Q(origin=F("destination")), name="transfers_dispatch_origin_ne_dest"
            ),
            models.CheckConstraint(
                condition=Q(status__in=[s.value for s in DispatchStatus]),
                name="transfers_dispatch_status_valid",
            ),
            models.CheckConstraint(
                condition=Q(decided_by__isnull=True, decided_at__isnull=True)
                | Q(decided_by__isnull=False, decided_at__isnull=False),
                name="transfers_dispatch_decided_pair",
            ),
        ]
        indexes = [
            models.Index(fields=["destination", "status"], name="transfers_dispatch_dest_idx"),
            models.Index(fields=["origin", "status"], name="transfers_dispatch_origin_idx"),
            models.Index(fields=["dispatched_at"], name="transfers_dispatch_at_idx"),
        ]


class DispatchLine(models.Model):
    """Its id is the ledger ``source_line_id`` for dispatch entries."""

    dispatch = models.ForeignKey(Dispatch, on_delete=models.PROTECT, related_name="lines")
    line_no = models.PositiveSmallIntegerField()
    item = models.ForeignKey("inventory.Item", on_delete=models.PROTECT, related_name="+")
    qty_dispatched = models.DecimalField(max_digits=12, decimal_places=3)
    qty_received = models.DecimalField(max_digits=12, decimal_places=3, null=True, blank=True)
    qty_accepted = models.DecimalField(max_digits=12, decimal_places=3, null=True, blank=True)
    qty_rejected = models.DecimalField(max_digits=12, decimal_places=3, null=True, blank=True)
    qty_resolved = models.DecimalField(max_digits=12, decimal_places=3, default=0)
    status = models.CharField(
        max_length=24, choices=LineStatus.choices, default=LineStatus.IN_TRANSIT
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["dispatch", "line_no"], name="transfers_dispatchline_no_uniq"
            ),
            models.CheckConstraint(
                condition=Q(qty_dispatched__gt=0), name="transfers_dispatchline_dispatched_ck"
            ),
            models.CheckConstraint(
                condition=Q(status__in=[s.value for s in LineStatus]),
                name="transfers_dispatchline_status_valid",
            ),
            # No overage (E3).
            models.CheckConstraint(
                condition=Q(qty_received__isnull=True)
                | Q(qty_received__gte=0, qty_received__lte=F("qty_dispatched")),
                name="transfers_dispatchline_received_ck",
            ),
            models.CheckConstraint(
                condition=Q(qty_accepted__isnull=True)
                | Q(qty_accepted__gte=0, qty_accepted__lte=F("qty_received")),
                name="transfers_dispatchline_accepted_ck",
            ),
            models.CheckConstraint(
                condition=Q(qty_rejected__isnull=True)
                | Q(qty_rejected=F("qty_received") - F("qty_accepted")),
                name="transfers_dispatchline_rejected_ck",
            ),
            models.CheckConstraint(
                condition=Q(qty_resolved__gte=0)
                & Q(qty_resolved__lte=F("qty_dispatched") - Coalesce(F("qty_accepted"), _ZERO)),
                name="transfers_dispatchline_resolved_ck",
            ),
            models.CheckConstraint(
                condition=Q(
                    qty_received__isnull=True, qty_accepted__isnull=True, qty_rejected__isnull=True
                )
                | Q(
                    qty_received__isnull=False,
                    qty_accepted__isnull=False,
                    qty_rejected__isnull=False,
                ),
                name="transfers_dispatchline_decision_all_or_none",
            ),
        ]
        indexes = [
            models.Index(fields=["item"], name="transfers_dline_item_idx"),
            models.Index(
                fields=["status"],
                name="transfers_dline_open_idx",
                condition=Q(status__in=["in_transit", "under_investigation"]),
            ),
        ]


class Discrepancy(models.Model):
    """One per line that has a shortfall or a rejection."""

    dispatch_line = models.OneToOneField(
        DispatchLine, on_delete=models.PROTECT, related_name="discrepancy"
    )
    qty_short = models.DecimalField(max_digits=12, decimal_places=3)
    qty_rejected = models.DecimalField(max_digits=12, decimal_places=3)
    note = models.TextField()
    flagged_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    flagged_at = models.DateTimeField()
    status = models.CharField(max_length=10, choices=DiscrepancyStatus.choices)

    class Meta:
        verbose_name_plural = "discrepancies"
        constraints = [
            models.CheckConstraint(
                condition=Q(qty_short__gte=0), name="transfers_discrepancy_short_ck"
            ),
            models.CheckConstraint(
                condition=Q(qty_rejected__gte=0), name="transfers_discrepancy_rejected_ck"
            ),
            models.CheckConstraint(
                condition=Q(qty_short__gt=0) | Q(qty_rejected__gt=0),
                name="transfers_discrepancy_something_wrong",
            ),
            models.CheckConstraint(
                condition=Q(status__in=[s.value for s in DiscrepancyStatus]),
                name="transfers_discrepancy_status_valid",
            ),
        ]


class DiscrepancyResolution(models.Model):
    """Append-only by service rule (no update or delete path). Id is the ledger line id."""

    discrepancy = models.ForeignKey(
        Discrepancy, on_delete=models.PROTECT, related_name="resolutions"
    )
    outcome = models.CharField(max_length=10, choices=ResolutionOutcome.choices)
    quantity = models.DecimalField(max_digits=12, decimal_places=3)
    note = models.TextField()
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    role_used = models.CharField(max_length=20)
    branch_context = models.ForeignKey(
        "branches.Branch", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    resolved_at = models.DateTimeField()
    operation = models.OneToOneField(
        "stock_ledger.Operation", on_delete=models.PROTECT, related_name="resolution"
    )

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(outcome__in=[o.value for o in ResolutionOutcome]),
                name="transfers_resolution_outcome_valid",
            ),
            models.CheckConstraint(
                condition=Q(quantity__gt=0), name="transfers_resolution_quantity_ck"
            ),
            models.CheckConstraint(
                condition=GreaterThan(Length(Trim("note")), 0),
                name="transfers_resolution_note_required",
            ),
        ]

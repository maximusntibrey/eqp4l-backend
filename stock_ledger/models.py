"""The idempotency record and the append-only stock ledger (ERD s3.8, s7).

Rows are inserted only by the stock service (B4.3). Updates and deletes are refused by the
model, the queryset and database triggers (migration ``0001``).
"""

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone

from eqp4l.append_only import AppendOnlyModel


class OperationType(models.TextChoices):
    SUPPLIER_RECEIPT = "supplier_receipt"
    DISPATCH = "dispatch"
    RECEIVE_DECISION = "receive_decision"
    DISCREPANCY_RESOLUTION = "discrepancy_resolution"
    SALE = "sale"
    SALE_CANCEL = "sale_cancel"
    OPENING_BALANCE_IMPORT = "opening_balance_import"


class Bucket(models.TextChoices):
    ON_HAND = "on_hand"
    RESERVED = "reserved"
    QUARANTINED = "quarantined"


class Reason(models.TextChoices):
    SUPPLIER_RECEIPT = "supplier_receipt"
    OPENING_BALANCE = "opening_balance"
    DISPATCH_RESERVE = "dispatch_reserve"
    DISPATCH_RECEIVED = "dispatch_received"
    DISCREPANCY_RETURN = "discrepancy_return"
    DISCREPANCY_LOSS = "discrepancy_loss"
    DISCREPANCY_DAMAGE = "discrepancy_damage"
    SALE = "sale"
    SALE_CANCEL = "sale_cancel"


class SourceType(models.TextChoices):
    GOODS_RECEIPT = "goods_receipt"
    DISPATCH = "dispatch"
    DISCREPANCY_RESOLUTION = "discrepancy_resolution"
    SALE = "sale"
    IMPORT_BATCH = "import_batch"


class Operation(AppendOnlyModel):
    """One row per stock-changing service call (idempotency, ERD s3.8)."""

    idempotency_key = models.UUIDField()
    operation_type = models.CharField(max_length=24, choices=OperationType.choices)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    request_hash = models.CharField(max_length=64)
    metadata = models.JSONField(default=dict)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["actor", "operation_type", "idempotency_key"],
                name="stock_ledger_operation_key_uniq",
            ),
            models.CheckConstraint(
                condition=Q(operation_type__in=[t.value for t in OperationType]),
                name="stock_ledger_operation_type_valid",
            ),
        ]


class Entry(AppendOnlyModel):
    """One row per bucket change; deltas of a bucket sum to its balance (ERD s3.8)."""

    operation = models.ForeignKey(Operation, on_delete=models.PROTECT, related_name="entries")
    idempotency_key = models.UUIDField()
    occurred_at = models.DateTimeField(default=timezone.now)
    location = models.ForeignKey(
        "branches.Branch", on_delete=models.PROTECT, related_name="ledger_entries"
    )
    item = models.ForeignKey(
        "inventory.Item", on_delete=models.PROTECT, related_name="ledger_entries"
    )
    bucket = models.CharField(max_length=12, choices=Bucket.choices)
    delta = models.DecimalField(max_digits=12, decimal_places=3)
    balance_after = models.DecimalField(max_digits=12, decimal_places=3)
    reason = models.CharField(max_length=30, choices=Reason.choices)
    source_type = models.CharField(max_length=30, choices=SourceType.choices)
    source_id = models.BigIntegerField()
    source_ref = models.CharField(max_length=30)
    source_line_id = models.BigIntegerField()
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    role_used = models.CharField(max_length=20)
    branch_context = models.ForeignKey(
        "branches.Branch", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    note = models.TextField(blank=True, default="")
    reverses = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="reversed_by"
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["operation", "source_line_id", "location", "item", "bucket", "reason"],
                name="stock_ledger_entry_no_double_post",
            ),
            models.UniqueConstraint(
                fields=["reverses"],
                condition=Q(reverses__isnull=False),
                name="stock_ledger_entry_reversed_once",
            ),
            models.CheckConstraint(
                condition=Q(bucket__in=[b.value for b in Bucket]),
                name="stock_ledger_entry_bucket_valid",
            ),
            models.CheckConstraint(condition=~Q(delta=0), name="stock_ledger_entry_delta_nonzero"),
            models.CheckConstraint(
                condition=Q(balance_after__gte=0), name="stock_ledger_entry_balance_after_ck"
            ),
            models.CheckConstraint(
                condition=Q(reason__in=[r.value for r in Reason]),
                name="stock_ledger_entry_reason_valid",
            ),
            models.CheckConstraint(
                condition=Q(source_type__in=[s.value for s in SourceType]),
                name="stock_ledger_entry_source_type_valid",
            ),
        ]
        indexes = [
            models.Index(
                fields=["item", "location", "occurred_at"], name="stock_ledger_entry_itemloc_idx"
            ),
            models.Index(fields=["location", "occurred_at"], name="stock_ledger_entry_loc_idx"),
            models.Index(fields=["source_type", "source_id"], name="stock_ledger_entry_source_idx"),
            models.Index(fields=["idempotency_key"], name="stock_ledger_entry_key_idx"),
            models.Index(fields=["actor", "occurred_at"], name="stock_ledger_entry_actor_idx"),
        ]

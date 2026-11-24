import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone

from config.append_only import AppendOnlyModel
from config.dbutils import choice_check


class Bucket(models.TextChoices):
    ON_HAND = "on_hand"
    RESERVED = "reserved"
    QUARANTINED = "quarantined"


class MovementType(models.TextChoices):
    SUPPLIER_RECEIPT = "supplier_receipt"
    OPENING_BALANCE = "opening_balance"
    DISPATCH = "dispatch"
    DISPATCH_RECEIPT = "dispatch_receipt"
    RESOLUTION_RETURN = "resolution_return"
    RESOLUTION_LOSS = "resolution_loss"
    RESOLUTION_DAMAGE = "resolution_damage"
    SALE = "sale"
    SALE_CANCELLATION = "sale_cancellation"


class SourceType(models.TextChoices):
    GOODS_RECEIPT = "goods_receipt"
    DISPATCH = "dispatch"
    DISPATCH_RESOLUTION = "dispatch_resolution"
    SALE = "sale"
    SALE_CANCELLATION = "sale_cancellation"
    CSV_IMPORT = "csv_import"


class StockMovement(AppendOnlyModel):
    """The ledger: one row per bucket changed. Inserts only; corrections are new rows (reverses_movement)."""

    created_at = models.DateTimeField(default=timezone.now)
    location = models.ForeignKey("branches.Location", on_delete=models.PROTECT, related_name="+")
    item = models.ForeignKey("inventory.Item", on_delete=models.PROTECT, related_name="+")
    bucket = models.CharField(max_length=20, choices=Bucket.choices)
    quantity_delta = models.IntegerField()
    balance_after = models.IntegerField()
    movement_type = models.CharField(max_length=30, choices=MovementType.choices)
    source_type = models.CharField(max_length=30, choices=SourceType.choices)
    source_id = models.BigIntegerField()  # for csv_import: import_batches.id
    source_ref = models.CharField(max_length=40, blank=True)
    source_line_id = models.BigIntegerField()  # for csv_import: the CSV row number
    operation_id = models.UUIDField(default=uuid.uuid4)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT, related_name="+")
    actor_role = models.CharField(max_length=30, blank=True)
    actor_location = models.ForeignKey(
        "branches.Location", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    reverses_movement = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="reversals"
    )
    note = models.TextField(blank=True)

    class Meta:
        constraints = [
            choice_check("bucket", Bucket, "movements_bucket_valid"),
            choice_check("movement_type", MovementType, "movements_type_valid"),
            choice_check("source_type", SourceType, "movements_source_valid"),
            models.CheckConstraint(condition=~models.Q(quantity_delta=0), name="movements_delta_not_zero"),
            models.CheckConstraint(
                condition=models.Q(balance_after__gte=0), name="movements_balance_non_negative"
            ),
            # A duplicate can never post twice (ERD s4).
            models.UniqueConstraint(
                fields=["source_type", "source_id", "source_line_id", "movement_type", "location", "bucket"],
                name="movements_no_double_post",
            ),
        ]
        indexes = [
            models.Index(fields=["location", "item", "created_at"], name="movements_loc_item_idx"),
            models.Index(fields=["operation_id"], name="movements_operation_idx"),
        ]


class IdempotencyKey(models.Model):
    """Looked up by (actor, scope, key) together, so one user can never read another's stored response."""

    key = models.UUIDField()
    scope = models.CharField(max_length=80)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    request_hash = models.CharField(max_length=64)
    response_status = models.IntegerField(null=True, blank=True)
    response_body = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["actor", "scope", "key"], name="idempotency_actor_scope_key")
        ]

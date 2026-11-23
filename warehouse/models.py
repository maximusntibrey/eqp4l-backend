import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone


class GoodsReceipt(models.Model):
    """A supplier receipt (GRN). Immutable once confirmed; corrections are adjustments (Sprint 4)."""

    reference = models.CharField(max_length=20, unique=True)  # GRN-000001
    location = models.ForeignKey("branches.Location", on_delete=models.PROTECT, related_name="+")
    supplier_name = models.CharField(max_length=150)
    notes = models.TextField(blank=True)
    received_at = models.DateTimeField(default=timezone.now)
    received_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    operation_id = models.UUIDField(unique=True, default=uuid.uuid4)


class GoodsReceiptLine(models.Model):
    receipt = models.ForeignKey(GoodsReceipt, on_delete=models.PROTECT, related_name="lines")
    item = models.ForeignKey("inventory.Item", on_delete=models.PROTECT, related_name="+")
    quantity = models.IntegerField()
    unit_cost = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=models.Q(quantity__gt=0), name="receipt_lines_qty_positive"),
            models.CheckConstraint(
                condition=models.Q(unit_cost__gte=0), name="receipt_lines_cost_non_negative"
            ),
        ]

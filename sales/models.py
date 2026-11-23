import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone

from config.dbutils import choice_check


class PaymentMethod(models.Model):
    """Configurable list (BE s6); seeded by post_migrate (config/reference_data.py)."""

    code = models.CharField(max_length=30, unique=True)
    name = models.CharField(max_length=60)
    is_active = models.BooleanField(default=True)


class SaleStatus(models.TextChoices):
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    REFUNDED = "refunded"
    EXCHANGED = "exchanged"


class Sale(models.Model):
    """Never edited; only status moves to cancelled through the cancel service."""

    reference = models.CharField(max_length=20, unique=True)  # SAL-000001
    location = models.ForeignKey("branches.Location", on_delete=models.PROTECT, related_name="+")
    staff = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    status = models.CharField(max_length=20, choices=SaleStatus.choices, default=SaleStatus.COMPLETED)
    payment_method = models.ForeignKey(PaymentMethod, on_delete=models.PROTECT, related_name="+")
    total = models.DecimalField(max_digits=12, decimal_places=2)
    sold_at = models.DateTimeField(default=timezone.now)
    operation_id = models.UUIDField(unique=True, default=uuid.uuid4)

    class Meta:
        constraints = [
            choice_check("status", SaleStatus, "sales_status_valid"),
            models.CheckConstraint(condition=models.Q(total__gte=0), name="sales_total_non_negative"),
        ]


class SaleLine(models.Model):
    sale = models.ForeignKey(Sale, on_delete=models.PROTECT, related_name="lines")
    item = models.ForeignKey("inventory.Item", on_delete=models.PROTECT, related_name="+")
    quantity = models.IntegerField()
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    line_total = models.DecimalField(max_digits=12, decimal_places=2)
    # average_cost copied at sale time (OQ-16), 4 dp; SA and WA only, API shows 2 dp.
    unit_cost_snapshot = models.DecimalField(max_digits=14, decimal_places=4)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=models.Q(quantity__gt=0), name="sale_lines_qty_positive"),
            models.CheckConstraint(
                condition=models.Q(unit_price__gte=0), name="sale_lines_price_non_negative"
            ),
            models.CheckConstraint(
                condition=models.Q(line_total__gte=0), name="sale_lines_total_non_negative"
            ),
            models.CheckConstraint(
                condition=models.Q(unit_cost_snapshot__gte=0), name="sale_lines_cost_non_negative"
            ),
        ]


class SaleCancellation(models.Model):
    sale = models.OneToOneField(Sale, on_delete=models.PROTECT, related_name="cancellation")
    reason = models.TextField()
    cancelled_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    cancelled_role = models.CharField(max_length=30)
    cancelled_at = models.DateTimeField(default=timezone.now)
    operation_id = models.UUIDField(unique=True, default=uuid.uuid4)

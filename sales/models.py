"""Sales (ERD s3.7). A completed sale is never edited; only the cancel transition exists."""

from django.conf import settings
from django.db import models
from django.db.models import CharField, F, Q, Value
from django.db.models.functions import Cast, Coalesce, Concat, Length, LPad, Round, Trim
from django.db.models.lookups import GreaterThan


class SaleStatus(models.TextChoices):
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    REFUNDED = "refunded"
    EXCHANGED = "exchanged"


class PaymentMethod(models.Model):
    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=50)
    is_active = models.BooleanField(default=True)

    def __str__(self) -> str:
        return str(self.code)


class Sale(models.Model):
    reference = models.GeneratedField(
        expression=Concat(Value("SAL-"), LPad(Cast("id", CharField()), 6, Value("0"))),
        output_field=CharField(max_length=20),
        db_persist=True,
        unique=True,
    )
    branch = models.ForeignKey("branches.Branch", on_delete=models.PROTECT, related_name="sales")
    sold_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="sales"
    )
    role_used = models.CharField(max_length=20)
    payment_method = models.ForeignKey(PaymentMethod, on_delete=models.PROTECT, related_name="+")
    total = models.DecimalField(max_digits=12, decimal_places=2)
    status = models.CharField(
        max_length=10,
        choices=SaleStatus.choices,
        default=SaleStatus.COMPLETED,
        db_default="completed",
    )
    sold_at = models.DateTimeField()
    cancelled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancel_reason = models.TextField(null=True, blank=True)  # noqa: DJ001 - ERD: null
    operation = models.OneToOneField(
        "stock_ledger.Operation", on_delete=models.PROTECT, related_name="sale"
    )
    cancel_operation = models.OneToOneField(
        "stock_ledger.Operation",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="cancelled_sale",
    )

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(total__gte=0), name="sales_sale_total_ck"),
            models.CheckConstraint(
                condition=Q(status__in=[s.value for s in SaleStatus]),
                name="sales_sale_status_valid",
            ),
            models.CheckConstraint(
                condition=~Q(status="cancelled")  # type: ignore[arg-type]
                | GreaterThan(Length(Trim(Coalesce("cancel_reason", Value("")))), 0),
                name="sales_sale_cancel_reason_required",
            ),
            models.CheckConstraint(
                condition=Q(status="cancelled", cancelled_at__isnull=False)
                | (~Q(status="cancelled") & Q(cancelled_at__isnull=True)),
                name="sales_sale_cancelled_at_matches",
            ),
        ]
        indexes = [
            models.Index(fields=["branch", "-sold_at"], name="sales_sale_branch_sold_idx"),
            models.Index(fields=["sold_by", "sold_at"], name="sales_sale_staff_sold_idx"),
            models.Index(fields=["status"], name="sales_sale_status_idx"),
        ]


class SaleLine(models.Model):
    sale = models.ForeignKey(Sale, on_delete=models.PROTECT, related_name="lines")
    line_no = models.PositiveSmallIntegerField()
    item = models.ForeignKey("inventory.Item", on_delete=models.PROTECT, related_name="+")
    quantity = models.DecimalField(max_digits=12, decimal_places=3)
    # Copied from the price list at sale time, never recomputed (ERD s5).
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    line_total = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["sale", "line_no"], name="sales_line_no_uniq"),
            models.CheckConstraint(condition=Q(quantity__gt=0), name="sales_line_quantity_ck"),
            models.CheckConstraint(condition=Q(unit_price__gte=0), name="sales_line_price_ck"),
            # Half-up to 2 dp, same as the service (Decimal ROUND_HALF_UP) and PostgreSQL round().
            models.CheckConstraint(
                condition=Q(line_total=Round(F("quantity") * F("unit_price"), 2)),
                name="sales_line_total_rule",
            ),
        ]
        indexes = [models.Index(fields=["item"], name="sales_line_item_idx")]

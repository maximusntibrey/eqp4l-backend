"""Items, stock balances and the price list (ERD s3.4, s5).

``StockBalance`` is the only mutable stock state. It is written only by the stock service
(B4.3); nothing else in the code base may touch it (ERD s8).
"""

from django.conf import settings
from django.contrib.postgres.indexes import GinIndex
from django.db import models
from django.db.models import F, Q
from django.db.models.functions import Lower, Now

from eqp4l.db import AuditFields


class Category(models.TextChoices):
    LAPTOP = "laptop"
    LAPTOP_PART = "laptop_part"
    ACCESSORY = "accessory"


class Condition(models.TextChoices):
    NEW = "new"
    REFURBISHED = "refurbished"
    USED = "used"


class ItemStatus(models.TextChoices):
    DRAFT = "draft"
    ACTIVE = "active"
    DISCONTINUED = "discontinued"


class PriceScope(models.TextChoices):
    CENTRAL = "central"
    BRANCH = "branch"


class Brand(models.Model):
    """Managed list (BE s3.2)."""

    name = models.CharField(max_length=100)

    class Meta:
        constraints = [models.UniqueConstraint(Lower("name"), name="inventory_brand_name_ci_uniq")]

    def __str__(self) -> str:
        return str(self.name)


class Subtype(models.Model):
    """Managed list of sub-types per category."""

    category = models.CharField(max_length=20, choices=Category.choices)
    name = models.CharField(max_length=100)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(category__in=[c.value for c in Category]),
                name="inventory_subtype_category_valid",
            ),
            models.UniqueConstraint(
                "category", Lower("name"), name="inventory_subtype_category_name_ci_uniq"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.category}: {self.name}"


class Item(AuditFields):
    """One SKU (the sellable configuration). No price and no cost columns (OQ-19, E7)."""

    sku = models.CharField(max_length=40, unique=True)
    name = models.CharField(max_length=200)
    category = models.CharField(max_length=20, choices=Category.choices)
    subtype = models.ForeignKey(Subtype, on_delete=models.PROTECT, related_name="items")
    brand = models.ForeignKey(Brand, on_delete=models.PROTECT, related_name="items")
    model_name = models.CharField(max_length=100)
    mpn = models.CharField(max_length=100)
    description = models.TextField(blank=True, default="")
    condition = models.CharField(max_length=12, choices=Condition.choices)
    uom = models.CharField(max_length=20, default="piece", db_default="piece")
    specs = models.JSONField(default=dict, db_default={})
    image_path = models.CharField(max_length=255, blank=True, default="")
    image_content_type = models.CharField(max_length=100, blank=True, default="")
    image_bytes = models.PositiveIntegerField(null=True, blank=True)
    show_on_website = models.BooleanField(default=False, db_default=False)
    search_keywords = models.TextField(blank=True, default="")
    status = models.CharField(
        max_length=12, choices=ItemStatus.choices, default=ItemStatus.DRAFT, db_default="draft"
    )

    class Meta:
        indexes = [
            models.Index(fields=["status"], name="inventory_item_status_idx"),
            models.Index(fields=["category", "brand"], name="inventory_item_cat_brand_idx"),
            # Trigram indexes for search by name, model or SKU (B6.3, B9.1).
            # (pg_trgm also serves case-insensitive ILIKE on the plain column.)
            GinIndex(fields=["name"], opclasses=["gin_trgm_ops"], name="inventory_item_name_trgm"),
            GinIndex(
                fields=["model_name"], opclasses=["gin_trgm_ops"], name="inventory_item_model_trgm"
            ),
            GinIndex(fields=["sku"], opclasses=["gin_trgm_ops"], name="inventory_item_sku_trgm"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(category__in=[c.value for c in Category]),
                name="inventory_item_category_valid",
            ),
            models.CheckConstraint(
                condition=Q(condition__in=[c.value for c in Condition]),
                name="inventory_item_condition_valid",
            ),
            models.CheckConstraint(
                condition=Q(status__in=[s.value for s in ItemStatus]),
                name="inventory_item_status_valid",
            ),
        ]

    def __str__(self) -> str:
        return str(self.sku)


class StockBalance(models.Model):
    """Quantities per SKU per location. ``available = on_hand - reserved`` is never stored."""

    item = models.ForeignKey(Item, on_delete=models.PROTECT, related_name="balances")
    location = models.ForeignKey(
        "branches.Branch", on_delete=models.PROTECT, related_name="balances"
    )
    on_hand = models.DecimalField(max_digits=12, decimal_places=3, default=0, db_default=0)
    reserved = models.DecimalField(max_digits=12, decimal_places=3, default=0, db_default=0)
    quarantined = models.DecimalField(max_digits=12, decimal_places=3, default=0, db_default=0)
    reorder_level = models.DecimalField(max_digits=12, decimal_places=3, null=True, blank=True)
    bin_label = models.CharField(max_length=50, null=True, blank=True)  # noqa: DJ001 - contract: null
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["item", "location"], name="inventory_balance_uniq"),
            models.CheckConstraint(
                condition=Q(on_hand__gte=0), name="inventory_balance_on_hand_ck"
            ),
            models.CheckConstraint(
                condition=Q(reserved__gte=0), name="inventory_balance_reserved_ck"
            ),
            models.CheckConstraint(
                condition=Q(reserved__lte=F("on_hand")),
                name="inventory_balance_reserved_le_on_hand",
            ),
            models.CheckConstraint(
                condition=Q(quarantined__gte=0), name="inventory_balance_quarantined_ck"
            ),
            models.CheckConstraint(
                condition=Q(reorder_level__isnull=True) | Q(reorder_level__gte=0),
                name="inventory_balance_reorder_level_ck",
            ),
        ]
        indexes = [
            models.Index(fields=["location"], name="inventory_balance_location_idx"),
            # Low-stock query: available <= reorder_level (B7.1).
            models.Index(
                fields=["location"],
                name="inventory_balance_lowstock_idx",
                condition=Q(reorder_level__isnull=False)
                & Q(on_hand__lte=F("reorder_level") + F("reserved")),
            ),
        ]


class Price(AuditFields):
    """The price list: one current central row per SKU (OQ-19, ERD s5)."""

    item = models.ForeignKey(Item, on_delete=models.PROTECT, related_name="prices")
    scope = models.CharField(
        max_length=10, choices=PriceScope.choices, default=PriceScope.CENTRAL, db_default="central"
    )
    branch = models.ForeignKey(
        "branches.Branch", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    effective_from = models.DateTimeField(db_default=Now())
    effective_to = models.DateTimeField(null=True, blank=True)
    set_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(scope__in=[s.value for s in PriceScope]),
                name="inventory_price_scope_valid",
            ),
            models.CheckConstraint(
                condition=Q(scope="central", branch__isnull=True)
                | Q(scope="branch", branch__isnull=False),
                name="inventory_price_scope_branch",
            ),
            models.CheckConstraint(condition=Q(amount__gte=0), name="inventory_price_amount_ck"),
            models.UniqueConstraint(
                fields=["item"],
                condition=Q(scope="central", effective_to__isnull=True),
                name="inventory_price_one_current_central",
            ),
            models.UniqueConstraint(
                fields=["item", "branch"],
                condition=Q(scope="branch", effective_to__isnull=True),
                name="inventory_price_one_current_branch",
            ),
        ]

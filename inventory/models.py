import uuid

from django.conf import settings
from django.db import models

from config.dbutils import choice_check


class Category(models.Model):
    name = models.CharField(max_length=50, unique=True)  # Laptop, Laptop Part, Accessory

    class Meta:
        verbose_name_plural = "categories"

    def __str__(self) -> str:
        return self.name


class Subtype(models.Model):
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="subtypes")
    name = models.CharField(max_length=80)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["category", "name"], name="subtypes_unique_name")]


class Brand(models.Model):
    name = models.CharField(max_length=80, unique=True)
    is_active = models.BooleanField(default=True)  # false = cannot be chosen for new items (OQ-20)

    def __str__(self) -> str:
        return self.name


class ItemStatus(models.TextChoices):
    DRAFT = "draft"
    ACTIVE = "active"
    DISCONTINUED = "discontinued"


class Condition(models.TextChoices):
    NEW = "new"
    REFURBISHED = "refurbished"
    USED = "used"


class Grade(models.TextChoices):
    A = "A"
    B = "B"
    C = "C"


class Item(models.Model):
    """One row per SKU (MVP). Cost is NOT here: it lives in ItemCost so BA/FS serializers cannot reach it."""

    sku = models.CharField(max_length=40, unique=True)
    name = models.CharField(max_length=200)
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="items")
    subtype = models.ForeignKey(
        Subtype, null=True, blank=True, on_delete=models.PROTECT, related_name="items"
    )
    brand = models.ForeignKey(Brand, on_delete=models.PROTECT, related_name="items")
    model_name = models.CharField(max_length=120, blank=True)
    mpn = models.CharField(max_length=80, blank=True)
    description = models.TextField(blank=True)
    condition = models.CharField(max_length=20, choices=Condition.choices, default=Condition.NEW)
    grade = models.CharField(max_length=1, choices=Grade.choices, null=True, blank=True)  # noqa: DJ001
    unit_of_measure = models.CharField(max_length=20, default="piece")
    status = models.CharField(max_length=20, choices=ItemStatus.choices, default=ItemStatus.DRAFT)
    key_specs = models.JSONField(default=dict, blank=True)
    image = models.CharField(max_length=255, blank=True)
    show_on_website = models.BooleanField(default=False)
    search_keywords = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )

    class Meta:
        constraints = [
            choice_check("status", ItemStatus, "items_status_valid"),
            choice_check("condition", Condition, "items_condition_valid"),
            choice_check("grade", Grade, "items_grade_valid"),
        ]

    def __str__(self) -> str:
        return self.sku


class ItemPrice(models.Model):
    """One selling-price row per SKU (GHS, 2 dp, never negative)."""

    item = models.OneToOneField(Item, on_delete=models.PROTECT, related_name="price")
    selling_price = models.DecimalField(max_digits=12, decimal_places=2)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )

    class Meta:
        constraints = [
            models.CheckConstraint(condition=models.Q(selling_price__gte=0), name="item_prices_non_negative")
        ]


class ItemCost(models.Model):
    """Average cost per SKU across all locations, numeric(14,4) (OQ-16). Never serialised for BA or FS."""

    item = models.OneToOneField(Item, primary_key=True, on_delete=models.PROTECT, related_name="cost")
    average_cost = models.DecimalField(max_digits=14, decimal_places=4)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=models.Q(average_cost__gte=0), name="item_costs_non_negative")
        ]


class StockBalance(models.Model):
    """Buckets per SKU per location. Written only by the stock service (stock_ledger.services)."""

    location = models.ForeignKey("branches.Location", on_delete=models.PROTECT, related_name="balances")
    item = models.ForeignKey(Item, on_delete=models.PROTECT, related_name="balances")
    on_hand = models.IntegerField(default=0)
    reserved = models.IntegerField(default=0)
    quarantined = models.IntegerField(default=0)
    bin_label = models.CharField(max_length=40, blank=True)
    reorder_level = models.IntegerField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["location", "item"], name="stock_balances_location_item"),
            models.CheckConstraint(condition=models.Q(on_hand__gte=0), name="stock_on_hand_non_negative"),
            models.CheckConstraint(condition=models.Q(reserved__gte=0), name="stock_reserved_non_negative"),
            models.CheckConstraint(
                condition=models.Q(reserved__lte=models.F("on_hand")), name="stock_reserved_within_on_hand"
            ),
            models.CheckConstraint(
                condition=models.Q(quarantined__gte=0), name="stock_quarantined_non_negative"
            ),
            models.CheckConstraint(
                condition=models.Q(reorder_level__isnull=True) | models.Q(reorder_level__gte=0),
                name="stock_reorder_level_non_negative",
            ),
        ]


class ImportBatch(models.Model):
    """One committed CSV import (FIX-9). Its id is the source_id of the csv_import ledger rows. Immutable."""

    reference = models.CharField(max_length=20, unique=True)  # IMP-000001
    kind = models.CharField(max_length=40, default="items_and_opening_stock")
    location = models.ForeignKey("branches.Location", on_delete=models.PROTECT, related_name="+")
    file_name = models.CharField(max_length=255, blank=True)
    row_count = models.IntegerField(default=0)
    imported_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT, related_name="+"
    )
    imported_at = models.DateTimeField(auto_now_add=True)
    operation_id = models.UUIDField(unique=True, default=uuid.uuid4)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=models.Q(row_count__gte=0), name="import_rows_non_negative")
        ]

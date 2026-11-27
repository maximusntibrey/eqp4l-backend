"""Item, brand and stock shapes (contract schemas Item, ItemWithCost, ItemWrite, Brand, StockBalance).

Cost lives only in the `*WithCost` classes, which only the SA/WA-only endpoints use.
"""

from decimal import Decimal
from typing import Any

from django.core.exceptions import ObjectDoesNotExist
from django.core.files.storage import default_storage
from rest_framework import serializers

from inventory.models import Brand, Category, Condition, Grade, Item, ItemStatus, StockBalance
from inventory.services import money
from stock_ledger.models import StockMovement


class CategorySerializer(serializers.ModelSerializer[Category]):
    class SubtypeSerializer(serializers.Serializer[object]):
        id = serializers.IntegerField()
        name = serializers.CharField()

    subtypes = SubtypeSerializer(many=True)

    class Meta:
        model = Category
        fields = ["id", "name", "subtypes"]


class BrandSerializer(serializers.ModelSerializer[Brand]):
    class Meta:
        model = Brand
        fields = ["id", "name", "is_active"]


class BrandWriteSerializer(serializers.Serializer[object]):
    name = serializers.CharField(max_length=80, required=False)  # the column holds 80
    is_active = serializers.BooleanField(required=False)


class FieldDefinitionSerializer(serializers.Serializer[Any]):
    key = serializers.CharField()
    label = serializers.CharField()  # type: ignore[assignment]
    type = serializers.ChoiceField(choices=["text", "integer", "decimal", "boolean", "choice"])
    required = serializers.BooleanField()  # type: ignore[assignment]
    choices = serializers.ListField(child=serializers.CharField(), required=False)
    group = serializers.CharField(allow_null=True)
    in_key_specs = serializers.BooleanField()


class ItemSerializer(serializers.ModelSerializer[Item]):
    category_id = serializers.IntegerField(read_only=True)
    subtype_id = serializers.IntegerField(read_only=True)
    brand_id = serializers.IntegerField(read_only=True)
    brand_name = serializers.CharField(source="brand.name", read_only=True)
    image_url = serializers.SerializerMethodField()
    selling_price = serializers.SerializerMethodField()

    class Meta:
        model = Item
        fields = [
            "id",
            "sku",
            "name",
            "category_id",
            "subtype_id",
            "brand_id",
            "brand_name",
            "model_name",
            "mpn",
            "description",
            "condition",
            "grade",
            "unit_of_measure",
            "status",
            "key_specs",
            "image_url",
            "show_on_website",
            "search_keywords",
            "selling_price",
            "created_at",
            "updated_at",
        ]

    def get_image_url(self, obj: Item) -> str | None:
        return default_storage.url(obj.image) if obj.image else None

    def get_selling_price(self, obj: Item) -> str | None:
        try:
            return money(obj.price.selling_price)
        except ObjectDoesNotExist:
            return None


class ItemWithCostSerializer(ItemSerializer):
    average_cost = serializers.SerializerMethodField()

    class Meta(ItemSerializer.Meta):
        fields = [*ItemSerializer.Meta.fields, "average_cost"]

    def get_average_cost(self, obj: Item) -> str | None:
        try:
            return money(obj.cost.average_cost)
        except ObjectDoesNotExist:
            return None


class WarningSerializer(serializers.Serializer[object]):
    code = serializers.ChoiceField(choices=["duplicate_name_model"])
    message = serializers.CharField()
    item_id = serializers.IntegerField()


class ItemWithCostAndWarningsSerializer(ItemWithCostSerializer):
    warnings = WarningSerializer(many=True)

    class Meta(ItemWithCostSerializer.Meta):
        fields = [*ItemWithCostSerializer.Meta.fields, "warnings"]


class ItemWriteSerializer(serializers.Serializer[object]):
    """Create needs the required fields (checked by the service); PATCH sends any subset."""

    sku = serializers.CharField(max_length=40, required=False)
    name = serializers.CharField(max_length=200, required=False)
    category_id = serializers.IntegerField(min_value=1, required=False)
    subtype_id = serializers.IntegerField(min_value=1, required=False)
    brand_id = serializers.IntegerField(min_value=1, required=False)
    model_name = serializers.CharField(max_length=120, required=False)
    mpn = serializers.CharField(max_length=80, required=False)
    description = serializers.CharField(allow_blank=True, required=False)
    condition = serializers.ChoiceField(choices=Condition.choices, required=False)
    grade = serializers.ChoiceField(choices=Grade.choices, allow_null=True, required=False)
    key_specs = serializers.DictField(required=False)
    show_on_website = serializers.BooleanField(required=False)
    search_keywords = serializers.CharField(allow_blank=True, required=False)
    selling_price = serializers.DecimalField(
        max_digits=12, decimal_places=2, min_value=Decimal(0), required=False
    )


class ItemQuerySerializer(serializers.Serializer[object]):
    q = serializers.CharField(required=False, allow_blank=True)
    status = serializers.ChoiceField(choices=ItemStatus.choices, required=False)
    category_id = serializers.IntegerField(required=False, min_value=1)
    brand_id = serializers.IntegerField(required=False, min_value=1)
    condition = serializers.ChoiceField(choices=Condition.choices, required=False)


STATUS_TARGETS = ["active", "discontinued"]


class StatusSerializer(serializers.Serializer[object]):
    status = serializers.ChoiceField(choices=STATUS_TARGETS)


class ImageSerializer(serializers.Serializer[object]):
    image = serializers.FileField()


class StockBalanceSerializer(serializers.ModelSerializer[StockBalance]):
    location_name = serializers.CharField(source="location.name")
    sku = serializers.CharField(source="item.sku")
    item_name = serializers.CharField(source="item.name")
    available = serializers.SerializerMethodField()
    low_stock = serializers.SerializerMethodField()

    class Meta:
        model = StockBalance
        fields = [
            "location_id",
            "location_name",
            "item_id",
            "sku",
            "item_name",
            "on_hand",
            "reserved",
            "available",
            "quarantined",
            "reorder_level",
            "low_stock",
        ]

    def get_available(self, obj: StockBalance) -> int:
        return obj.on_hand - obj.reserved

    def get_low_stock(self, obj: StockBalance) -> bool:
        return obj.reorder_level is not None and obj.on_hand - obj.reserved <= obj.reorder_level


class StockBalanceWithCostSerializer(StockBalanceSerializer):
    average_cost = serializers.SerializerMethodField()

    class Meta(StockBalanceSerializer.Meta):
        fields = [*StockBalanceSerializer.Meta.fields, "average_cost"]

    def get_average_cost(self, obj: StockBalance) -> str | None:
        try:
            return money(obj.item.cost.average_cost)
        except ObjectDoesNotExist:
            return None


class BranchAvailabilitySerializer(serializers.Serializer[object]):
    branch_id = serializers.IntegerField()
    branch_name = serializers.CharField()
    kind = serializers.ChoiceField(choices=["branch", "warehouse"])
    quantity = serializers.IntegerField(min_value=0)


class StockMovementSerializer(serializers.ModelSerializer[StockMovement]):
    location_name = serializers.CharField(source="location.name")
    sku = serializers.CharField(source="item.sku")
    item_name = serializers.CharField(source="item.name")
    actor_login_id = serializers.SerializerMethodField()

    class Meta:
        model = StockMovement
        fields = [
            "id",
            "created_at",
            "location_id",
            "location_name",
            "item_id",
            "sku",
            "item_name",
            "bucket",
            "quantity_delta",
            "balance_after",
            "movement_type",
            "source_type",
            "source_ref",
            "actor_login_id",
            "note",
        ]

    def get_actor_login_id(self, obj: StockMovement) -> str:
        return obj.actor.login_id if obj.actor else ""

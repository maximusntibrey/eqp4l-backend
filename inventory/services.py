"""Item API rules (B4.1, B4.2; PERMISSION_TABLE rows 13-16, 43).

Items start as Draft; Draft -> Active needs the image and every required field; Active -> Discontinued is
final. Cost is never read here: it lives in ItemCost and only the cost serializers touch it. Audit events:
item_created, item_updated, item_status_changed, item_image_set, brand_created, brand_updated.
"""

import re
import uuid
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import IntegrityError, transaction
from django.db.models import Q, QuerySet
from django.http import HttpRequest
from PIL import Image, UnidentifiedImageError
from rest_framework.exceptions import ValidationError

from accounts.models import LoginIdSequence, User
from audit.services import record_event
from config.errors import ApiError
from inventory.catalog import KEY_SPECS, FieldDef
from inventory.models import Brand, Category, Item, ItemPrice, ItemStatus, Subtype
from roles.permissions import require_action
from roles.services import active_role
from sales.models import SaleLine
from stock_ledger.models import StockMovement
from transfers.models import DispatchLine
from warehouse.models import GoodsReceiptLine

REQUIRED_ON_CREATE = ("name", "category_id", "subtype_id", "brand_id", "model_name", "mpn", "condition")
MAX_IMAGE_BYTES = 5 * 1024 * 1024
IMAGE_FORMATS = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp"}
_TEXT_MAX = 200


def money(value: Decimal | None) -> str | None:
    """GHS with exactly 2 decimals (average cost is stored at 4 dp, shown at 2 dp)."""
    return None if value is None else str(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _role(actor: User) -> str:
    return active_role(actor) or ""


def _audit(request: HttpRequest, actor: User, action: str, item: Item, **values: Any) -> None:
    record_event(
        action,
        request=request,
        actor=actor,
        actor_role=_role(actor),
        target_type="item",
        target_ref=item.sku,
        **values,
    )


def snapshot(item: Item) -> dict[str, Any]:
    price = ItemPrice.objects.filter(item=item).values_list("selling_price", flat=True).first()
    return {
        "sku": item.sku,
        "name": item.name,
        "category_id": item.category_id,
        "subtype_id": item.subtype_id,
        "brand_id": item.brand_id,
        "model_name": item.model_name,
        "mpn": item.mpn,
        "description": item.description,
        "condition": item.condition,
        "grade": item.grade,
        "status": item.status,
        "key_specs": item.key_specs,
        "show_on_website": item.show_on_website,
        "search_keywords": item.search_keywords,
        "selling_price": money(price),
    }


# ---- queries --------------------------------------------------------------------------------------------


def item_queryset() -> QuerySet[Item]:
    return Item.objects.select_related("brand", "price", "cost").order_by("id")


def search_items(params: dict[str, Any]) -> QuerySet[Item]:
    qs = item_queryset()
    if params.get("q"):
        q = params["q"].strip()
        qs = qs.filter(
            Q(name__icontains=q)
            | Q(sku__icontains=q)
            | Q(brand__name__icontains=q)
            | Q(model_name__icontains=q)
            | Q(mpn__icontains=q)
        )
    for field in ("status", "category_id", "brand_id", "condition"):
        if params.get(field) not in (None, ""):
            qs = qs.filter(**{field: params[field]})
    return qs


def item_in_use(item: Item) -> bool:
    """True once the item appears in any transaction: SKU is then immutable (ERD s5)."""
    return any(
        model.objects.filter(item=item).exists()
        for model in (StockMovement, DispatchLine, SaleLine, GoodsReceiptLine)
    )


# ---- validation -----------------------------------------------------------------------------------------


def _check_spec(definition: FieldDef, value: Any) -> Any:
    kind = definition.type
    if kind == "integer" and isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    if kind == "boolean" and isinstance(value, bool):
        return value
    if kind == "text" and isinstance(value, str) and value.strip():
        if len(value.strip()) <= _TEXT_MAX:
            return value.strip()
        raise ValueError(f"Use at most {_TEXT_MAX} characters.")
    if kind == "choice" and value in definition.choices:
        return value
    if kind == "decimal" and not isinstance(value, bool) and isinstance(value, (int, float, str)):
        try:
            number = Decimal(str(value))
        except ArithmeticError:
            raise ValueError("Enter a number.") from None
        if number.is_finite() and number >= 0:
            return str(number)  # JSON keeps it exact as text
    raise ValueError("Choose one of the listed values." if kind == "choice" else f"Enter a valid {kind}.")


def validate_key_specs(category_name: str, specs: Any) -> dict[str, Any]:
    """Unknown keys and wrong types are refused; empty values are dropped. Required-ness is for activation."""
    if not isinstance(specs, dict):
        raise ValidationError({"key_specs": ["Send the key specs as an object."]})
    definitions = {d.key: d for d in KEY_SPECS.get(category_name, [])}
    errors: dict[str, list[str]] = {}
    clean: dict[str, Any] = {}
    for key, value in specs.items():
        if key not in definitions:
            errors[key] = ["This is not a key spec of this category."]
        elif value is None or value == "":
            continue
        else:
            try:
                clean[key] = _check_spec(definitions[key], value)
            except ValueError as exc:
                errors[key] = [str(exc)]
    if errors:
        raise ValidationError({"key_specs": errors})
    return clean


def _clean(data: dict[str, Any], item: Item | None) -> dict[str, Any]:
    """Resolve and check references and key specs; returns the model fields to set."""
    changes = {k: v for k, v in data.items() if k not in ("selling_price", "key_specs")}
    category = item.category if item else None
    if "category_id" in changes:
        category = Category.objects.filter(pk=changes.pop("category_id")).first()
        if category is None:
            raise ApiError(400, "validation_error", "Choose a category.", "category_id")
        changes["category"] = category
    if category is None:
        raise ApiError(400, "validation_error", "Choose a category.", "category_id")
    # An imported or seeded item may have no sub-type: editing it must not force one (PATCH was 400).
    keep_empty = item is not None and "subtype_id" not in changes and item.subtype_id is None
    subtype_id = changes.pop("subtype_id", item.subtype_id if item else None)
    subtype = None if keep_empty else Subtype.objects.filter(pk=subtype_id, category=category).first()
    if subtype is None and not keep_empty:
        raise ApiError(
            400, "validation_error", "Choose a sub-type that belongs to the category.", "subtype_id"
        )
    changes["subtype"] = subtype
    if "brand_id" in changes:
        brand = Brand.objects.filter(pk=changes.pop("brand_id")).first()
        if brand is None or (not brand.is_active and (item is None or item.brand_id != brand.pk)):
            raise ApiError(400, "validation_error", "Choose an active brand.", "brand_id")
        changes["brand"] = brand
    if "key_specs" in data or item is None or category != item.category:
        changes["key_specs"] = validate_key_specs(category.name, data.get("key_specs", {}))
    if "sku" in changes:
        sku = changes["sku"].strip()
        clash = Item.objects.filter(sku__iexact=sku)
        if item is not None:
            clash = clash.exclude(pk=item.pk)
        if clash.exists():
            raise ApiError(409, "conflict", "That SKU is already in use.", "sku")
        changes["sku"] = sku
    return changes


def duplicate_warnings(item: Item) -> list[dict[str, Any]]:
    """Near-identical name and model (letters and digits only, any case). Never blocks."""

    def norm(text: str) -> str:
        return re.sub(r"[^a-z0-9]", "", text.lower())

    twins = Item.objects.filter(model_name__iexact=item.model_name).exclude(pk=item.pk)
    return [
        {
            "code": "duplicate_name_model",
            "message": f"{other.sku} has the same name and model.",
            "item_id": other.pk,
        }
        for other in twins
        if norm(other.name) == norm(item.name)
    ]


def _next_sku() -> str:
    """SKU-000001 style, from the same never-decreasing counter table as login IDs (prefix SKU)."""
    while True:
        with transaction.atomic():
            seq, _ = LoginIdSequence.objects.select_for_update().get_or_create(prefix="SKU")
            seq.last_number += 1
            seq.save(update_fields=["last_number"])
        sku = f"SKU-{seq.last_number:06d}"
        if not Item.objects.filter(sku__iexact=sku).exists():  # an imported SKU may already hold the number
            return sku


def _set_price(item: Item, price: Decimal | None, actor: User) -> None:
    if price is not None:
        ItemPrice.objects.update_or_create(item=item, defaults={"selling_price": price, "updated_by": actor})


# ---- item operations ------------------------------------------------------------------------------------


def create_item(request: HttpRequest, actor: User, data: dict[str, Any]) -> tuple[Item, list[dict[str, Any]]]:
    require_action(actor, "items.manage")
    if "selling_price" in data:
        require_action(actor, "prices.manage")  # row 16: SA or a Manage prices holder
    for field in REQUIRED_ON_CREATE:
        if field not in data:
            raise ApiError(400, "validation_error", "This field is required.", field)
    try:
        with transaction.atomic():
            fields = _clean(data, None)
            fields["sku"] = fields.get("sku") or _next_sku()
            item = Item.objects.create(status=ItemStatus.DRAFT, created_by=actor, updated_by=actor, **fields)
            _set_price(item, data.get("selling_price"), actor)
            _audit(request, actor, "item_created", item, after=snapshot(item))
    except IntegrityError:  # a concurrent create took the SKU first
        raise ApiError(409, "conflict", "That SKU is already in use.", "sku") from None
    return item, duplicate_warnings(item)


def _locked(item_id: int) -> Item:
    item = Item.objects.select_for_update().filter(pk=item_id).first()
    if item is None:
        raise ApiError(404, "not_found", "No such item.")
    return item


def update_item(
    request: HttpRequest, actor: User, item_id: int, data: dict[str, Any]
) -> tuple[Item, list[dict[str, Any]]]:
    require_action(actor, "items.manage")
    if "selling_price" in data:
        require_action(actor, "prices.manage")
    try:
        with transaction.atomic():
            item = _locked(item_id)
            if item.status == ItemStatus.DISCONTINUED:
                raise ApiError(409, "conflict", "A discontinued item cannot be edited.")
            before = snapshot(item)
            fields = _clean(data, item)
            if fields.get("sku", item.sku) != item.sku and item_in_use(item):
                raise ApiError(400, "validation_error", "The SKU cannot change once the item is used.", "sku")
            for name, value in fields.items():
                setattr(item, name, value)
            item.updated_by = actor
            item.save()
            _set_price(item, data.get("selling_price"), actor)
            _audit(request, actor, "item_updated", item, before=before, after=snapshot(item))
    except IntegrityError:
        raise ApiError(409, "conflict", "That SKU is already in use.", "sku") from None
    return item, duplicate_warnings(item)


def set_status(request: HttpRequest, actor: User, item_id: int, status: str) -> Item:
    require_action(actor, "items.manage")
    with transaction.atomic():
        item = _locked(item_id)
        allowed: dict[str, str] = {"draft": "active", "active": "discontinued"}
        if allowed.get(item.status) != status:
            raise ApiError(409, "conflict", f"A {item.status} item cannot become {status}.")
        if status == ItemStatus.ACTIVE:
            _require_complete(item)
        before = snapshot(item)
        item.status, item.updated_by = status, actor
        item.save(update_fields=["status", "updated_by", "updated_at"])
        _audit(request, actor, "item_status_changed", item, before=before, after=snapshot(item))
    return item


def _require_complete(item: Item) -> None:
    errors: dict[str, Any] = {}
    if not item.image:
        errors["image"] = ["Upload the item image first."]
    missing = {
        d.key: ["This spec is needed to activate the item."]
        for d in KEY_SPECS.get(item.category.name, [])
        if d.required and d.key not in item.key_specs
    }
    if missing:
        errors["key_specs"] = missing
    if errors:
        raise ValidationError(errors)


def store_image(request: HttpRequest, actor: User, item_id: int, upload: Any) -> Item:
    """One image per item: JPEG, PNG or WebP by content, at most 5 MB. The client file name is never used."""
    require_action(actor, "items.manage")
    if upload.size > MAX_IMAGE_BYTES:
        raise ApiError(413, "file_too_large", "The image is larger than 5 MB.", "image")
    try:
        with Image.open(upload) as picture:
            picture.verify()
            extension = IMAGE_FORMATS.get(picture.format or "")
    except (UnidentifiedImageError, OSError, SyntaxError, Image.DecompressionBombError):
        extension = None
    if extension is None:
        raise ApiError(400, "validation_error", "Upload a JPEG, PNG or WebP image.", "image")
    upload.seek(0)
    with transaction.atomic():
        item = _locked(item_id)
        if item.status == ItemStatus.DISCONTINUED:
            raise ApiError(409, "conflict", "A discontinued item cannot be edited.")
        before = item.image
        # shortcut: the old file stays on disk (images are removed from view, not deleted, BE 3.6)
        name = default_storage.save(
            f"items/{item.pk}-{uuid.uuid4().hex}.{extension}", ContentFile(upload.read())
        )
        try:
            item.image = name
            item.updated_by = actor
            item.save(update_fields=["image", "updated_by", "updated_at"])
            _audit(request, actor, "item_image_set", item, before={"image": before}, after={"image": name})
        except BaseException:
            default_storage.delete(name)  # the transaction rolls back, so the new file must not outlive it
            raise
    return item


# ---- brands ---------------------------------------------------------------------------------------------


def _brand_values(brand: Brand) -> dict[str, Any]:
    return {"name": brand.name, "is_active": brand.is_active}


def save_brand(request: HttpRequest, actor: User, data: dict[str, Any], brand: Brand | None = None) -> Brand:
    """Create (name required) or update a brand (rename, deactivate, reactivate). Never deleted (OQ-20)."""
    require_action(actor, "items.manage")
    if brand is None and "name" not in data:
        raise ApiError(400, "validation_error", "Enter a name.", "name")
    if not data:
        raise ApiError(400, "validation_error", "Send a name or is_active to change.")
    if "name" in data:
        clash = Brand.objects.filter(name__iexact=data["name"])
        if brand is not None:
            clash = clash.exclude(pk=brand.pk)
        if clash.exists():
            raise ApiError(400, "validation_error", "That brand already exists.", "name")
    try:
        with transaction.atomic():
            before = _brand_values(brand) if brand else None
            if brand is None:
                brand = Brand(**data)
            else:
                brand = Brand.objects.select_for_update().get(pk=brand.pk)
                for name, value in data.items():
                    setattr(brand, name, value)
            brand.save()
            record_event(
                "brand_updated" if before else "brand_created",
                request=request,
                actor=actor,
                actor_role=_role(actor),
                target_type="brand",
                target_ref=brand.name,
                before=before,
                after=_brand_values(brand),
            )
    except IntegrityError:
        raise ApiError(400, "validation_error", "That brand already exists.", "name") from None
    return brand

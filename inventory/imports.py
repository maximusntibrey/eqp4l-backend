"""CSV import of items and opening quantities for one location (B6.4; PERMISSION_TABLE rows 19, 20).

Every row is checked in its own savepoint and all errors are reported with the CSV row number (the header is
row 1). Nothing is kept unless the whole file is clean and `dry_run` is false: a dry run, and any file with
errors, is rolled back. Opening quantities are ledger movements (opening_balance, source csv_import, source_id
the batch, source_line_id the CSV row); the unit cost is folded into the average cost BEFORE the stock is
posted. Audit event: csv_import_committed (plus item_created per new item and stock_posted).
"""

import csv
import io
import re
import uuid
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from django.core.files.uploadedfile import UploadedFile
from django.db import transaction
from django.http import HttpRequest
from rest_framework.exceptions import ValidationError

from accounts.models import LoginIdSequence, User
from audit.services import record_event
from branches.models import Location, LocationKind
from config.errors import ApiError, flatten
from inventory import services
from inventory.models import Brand, Category, Condition, ImportBatch, Item, ItemStatus, StockBalance, Subtype
from roles.permissions import has_action, require_action, require_location
from roles.services import active_role
from stock_ledger.models import Bucket, MovementType, SourceType
from stock_ledger.services import StockChange, post_stock_changes
from warehouse.services import fold_average_cost

EXTRA = "_extra"
MAX_BYTES = 2 * 1024 * 1024
MAX_ROWS = 5000
MAX_QUANTITY = 1_000_000
ITEM_COLUMNS = ["name", "category", "subtype", "brand", "model_name", "mpn", "condition"]
REQUIRED_COLUMNS = ["opening_quantity", "unit_cost"]
OPTIONAL_COLUMNS = ["sku", "selling_price", "reorder_level", "bin_label"]
COLUMNS = ITEM_COLUMNS + REQUIRED_COLUMNS + OPTIONAL_COLUMNS
MAX_LENGTH = {"sku": 40, "name": 200, "model_name": 120, "mpn": 80, "bin_label": 40}
MONEY = re.compile(r"^\d{1,10}(\.\d{1,2})?$")
WHOLE = re.compile(r"^\d{1,7}$")


@dataclass
class RowPlan:
    line_no: int
    item: Item
    quantity: int
    reorder_level: int | None
    bin_label: str
    created: bool
    unit_cost: Decimal


def _parse(upload: UploadedFile) -> list[tuple[int, dict[str, str]]]:
    if upload.size is not None and upload.size > MAX_BYTES:
        raise ApiError(413, "file_too_large", "The file is larger than 2 MB.", "file")
    try:
        text = upload.read().decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ApiError(400, "validation_error", "Save the file as UTF-8 CSV.", "file") from None
    reader = csv.DictReader(io.StringIO(text), restkey=EXTRA)
    header = [h.strip() for h in (reader.fieldnames or [])]
    if not header:
        raise ApiError(400, "validation_error", "The file is empty.", "file")
    repeated = sorted({h for h in header if header.count(h) > 1})
    if repeated:
        raise ApiError(400, "validation_error", f"Repeated columns: {', '.join(repeated)}.", "file")
    unknown = [h for h in header if h not in COLUMNS]
    missing = [h for h in REQUIRED_COLUMNS if h not in header]
    if unknown or missing:
        problem = (f"Unknown columns: {', '.join(unknown)}. " if unknown else "") + (
            f"Missing columns: {', '.join(missing)}." if missing else ""
        )
        raise ApiError(400, "validation_error", problem.strip(), "file")
    reader.fieldnames = header
    rows: list[tuple[int, dict[str, str]]] = []
    try:
        for number, row in enumerate(reader, start=2):
            if len(rows) >= MAX_ROWS:
                raise ApiError(400, "validation_error", f"At most {MAX_ROWS} rows per file.", "file")
            if any((v or "").strip() for v in row.values() if isinstance(v, str)):
                cells = {k: (v or "").strip() for k, v in row.items() if isinstance(v, str)}
                if row.get(EXTRA):
                    cells[EXTRA] = "1"
                rows.append((number, cells))
    except csv.Error:
        raise ApiError(400, "validation_error", "The file is not a valid CSV.", "file") from None
    if not rows:
        raise ApiError(400, "validation_error", "The file has no data rows.", "file")
    return rows


def _whole(value: str, field: str) -> int:
    if not WHOLE.match(value) or int(value) > MAX_QUANTITY:
        raise ApiError(400, "validation_error", f"Enter a whole number from 0 to {MAX_QUANTITY}.", field)
    return int(value)


def _money(value: str, field: str) -> Decimal:
    if not MONEY.match(value):
        raise ApiError(400, "validation_error", "Enter an amount with at most 2 decimals, 0 or more.", field)
    try:
        return Decimal(value)
    except InvalidOperation:  # pragma: no cover - the pattern already guarantees a number
        raise ApiError(400, "validation_error", "Enter an amount.", field) from None


def _lookup(row: dict[str, str]) -> dict[str, Any]:
    """Item fields of a NEW item, names resolved to ids. Errors name the column."""
    for column in ITEM_COLUMNS:
        if not row.get(column):
            raise ApiError(400, "validation_error", "This column is needed for a new item.", column)
    for column, limit in MAX_LENGTH.items():
        if len(row.get(column, "")) > limit:
            raise ApiError(400, "validation_error", f"Use at most {limit} characters.", column)
    category = Category.objects.filter(name__iexact=row["category"]).first()
    if category is None:
        raise ApiError(400, "validation_error", "Unknown category.", "category")
    subtype = Subtype.objects.filter(category=category, name__iexact=row["subtype"]).first()
    if subtype is None:
        raise ApiError(400, "validation_error", "Unknown sub-type for that category.", "subtype")
    brand = Brand.objects.filter(name__iexact=row["brand"], is_active=True).first()
    if brand is None:
        raise ApiError(400, "validation_error", "Unknown or inactive brand.", "brand")
    condition = row["condition"].lower()
    if condition not in Condition.values:
        raise ApiError(400, "validation_error", f"Use one of: {', '.join(Condition.values)}.", "condition")
    data: dict[str, Any] = {
        "name": row["name"],
        "category_id": category.pk,
        "subtype_id": subtype.pk,
        "brand_id": brand.pk,
        "model_name": row["model_name"],
        "mpn": row["mpn"],
        "condition": condition,
    }
    if row.get("sku"):
        data["sku"] = row["sku"]
    if row.get("selling_price"):
        data["selling_price"] = _money(row["selling_price"], "selling_price")
    return data


def _plan_row(
    request: HttpRequest,
    actor: User,
    location: Location,
    line_no: int,
    row: dict[str, str],
    seen: set[int],
) -> RowPlan:
    if row.get(EXTRA):
        raise ApiError(400, "validation_error", "This row has extra cells beyond the header.", None)
    quantity = _whole(row.get("opening_quantity", ""), "opening_quantity")
    if not row.get("unit_cost"):
        raise ApiError(400, "validation_error", "The unit cost is required.", "unit_cost")
    unit_cost = _money(row["unit_cost"], "unit_cost")
    reorder = _whole(row["reorder_level"], "reorder_level") if row.get("reorder_level") else None
    bin_label = row.get("bin_label", "")
    if len(bin_label) > MAX_LENGTH["bin_label"]:
        raise ApiError(400, "validation_error", "Use at most 40 characters.", "bin_label")
    if bin_label and location.kind != LocationKind.WAREHOUSE:
        raise ApiError(400, "validation_error", "A bin label is for warehouse rows only.", "bin_label")
    existing = Item.objects.filter(sku__iexact=row["sku"]).first() if row.get("sku") else None
    if existing is not None:
        if existing.status == ItemStatus.DISCONTINUED:
            raise ApiError(400, "validation_error", "A discontinued item cannot receive stock.", "sku")
        if row.get("selling_price"):
            raise ApiError(
                400,
                "validation_error",
                "Change the price of an existing item on the item screen.",
                "selling_price",
            )
        item, created = existing, False
    else:
        if row.get("selling_price") and not has_action(actor, "prices.manage"):
            raise ApiError(403, "permission_denied", "You are not allowed to set prices.", "selling_price")
        item, _ = services.create_item(request, actor, _lookup(row))
        created = True
    if item.pk in seen:
        raise ApiError(400, "validation_error", "This SKU appears twice in the file.", "sku")
    seen.add(item.pk)
    return RowPlan(line_no, item, quantity, reorder, bin_label, created, unit_cost)


def _next_reference() -> str:
    seq, _ = LoginIdSequence.objects.select_for_update().get_or_create(prefix="IMP")
    seq.last_number += 1
    seq.save(update_fields=["last_number"])
    return f"IMP-{seq.last_number:06d}"


def import_items(
    request: HttpRequest,
    actor: User,
    *,
    upload: UploadedFile,
    location_id: int | None,
    dry_run: bool,
    operation_id: uuid.UUID,
) -> dict[str, Any]:
    """Check one import, commit only when `dry_run` is false and the file is clean. Returns the report."""
    require_action(actor, "items.import")  # SA and WA (rows 19, 20)
    if location_id is None:
        location = actor.permanent_location
        if location is None:
            raise ApiError(400, "validation_error", "Choose the location to load.", "location_id")
    else:
        location = Location.objects.filter(pk=location_id, is_active=True).first()
        if location is None:
            raise ApiError(400, "validation_error", "Choose an active location.", "location_id")
    require_location(actor, location, request.session)
    rows = _parse(upload)
    role = active_role(actor) or ""
    errors: list[dict[str, Any]] = []
    plans: list[RowPlan] = []
    seen: set[int] = set()
    reference: str | None = None
    with transaction.atomic():
        for line_no, row in rows:
            try:
                with transaction.atomic():  # a failed row leaves nothing behind
                    plans.append(_plan_row(request, actor, location, line_no, row, seen))
            except ApiError as exc:
                errors.append({"row": line_no, "field": exc.field, "message": exc.message})
            except ValidationError as exc:
                errors += [{"row": line_no, **e} for e in flatten(exc.detail)]
        if errors or dry_run:
            transaction.set_rollback(True)
        else:
            reference = _commit(request, actor, role, location, plans, len(rows), upload, operation_id)
    return {
        "dry_run": dry_run,
        "committed": reference is not None,
        "batch_reference": reference,
        "location_id": location.pk,
        "rows": len(rows),
        "items_created": sum(p.created for p in plans),
        "items_existing": sum(not p.created for p in plans),
        "opening_quantity_total": sum(p.quantity for p in plans),
        "errors": errors,
    }


def _commit(
    request: HttpRequest,
    actor: User,
    role: str,
    location: Location,
    plans: list[RowPlan],
    row_count: int,
    upload: UploadedFile,
    operation_id: uuid.UUID,
) -> str:
    batch = ImportBatch.objects.create(
        reference=_next_reference(),
        location=location,
        file_name=(upload.name or "")[:255],
        row_count=row_count,
        imported_by=actor,
        operation_id=operation_id,
    )
    stocked = [p for p in plans if p.quantity]
    # Same lock order as a receipt (cost rows by item id, then balances): no deadlock between the two.
    # The cost row exists before any stock is posted; a dry run never gets here, so it takes no cost locks.
    for p in sorted(stocked, key=lambda plan: plan.item.pk):
        fold_average_cost(p.item, p.quantity, p.unit_cost)
    if stocked:
        post_stock_changes(
            [
                StockChange(
                    location=location,
                    item=p.item,
                    bucket=Bucket.ON_HAND,
                    delta=p.quantity,
                    movement_type=MovementType.OPENING_BALANCE,
                    source_type=SourceType.CSV_IMPORT,
                    source_id=batch.pk,
                    source_line_id=p.line_no,
                    source_ref=batch.reference,
                )
                for p in stocked
            ],
            actor=actor,
            actor_role=role,
            actor_location=location,
            operation_id=operation_id,
            note=batch.reference,
        )
    for p in plans:  # labels only; quantities are never written outside the stock service
        meta = {
            k: v
            for k, v in (("reorder_level", p.reorder_level), ("bin_label", p.bin_label))
            if v not in (None, "")
        }
        if meta:
            StockBalance.objects.update_or_create(location=location, item=p.item, defaults=meta)
    record_event(
        "csv_import_committed",
        request=request,
        actor=actor,
        actor_role=role,
        location=location,
        target_type="import_batch",
        target_ref=batch.reference,
        after={
            "rows": row_count,
            "items_created": sum(p.created for p in plans),
            "opening_quantity_total": sum(p.quantity for p in plans),
        },  # no cost in the audit trail
        operation_id=operation_id,
    )
    return batch.reference

"""Warehouse receipts (B5.1): one atomic operation per GRN.

Receipt, lines, average cost, balances, ledger rows and audit rows commit together or not at all. Stock
itself is only ever changed through `stock_ledger.services.post_stock_changes`.
"""

import uuid
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from django.db import transaction
from django.db.models import Sum
from django.http import HttpRequest

from accounts.models import User
from audit.services import record_event
from branches.models import Location, LocationKind
from config.errors import ApiError
from inventory.models import Item, ItemCost, ItemStatus, StockBalance
from roles.permissions import require_action, require_location
from roles.services import active_role
from stock_ledger.models import Bucket, MovementType, SourceType
from stock_ledger.services import StockChange, post_stock_changes
from warehouse.models import GoodsReceipt, GoodsReceiptLine

FOUR_DP = Decimal("0.0001")


def active_warehouse() -> Location:
    warehouse = Location.objects.filter(kind=LocationKind.WAREHOUSE, is_active=True).first()
    if warehouse is None:
        raise ApiError(409, "conflict", "There is no active warehouse.")
    return warehouse


def active_items(lines: list[dict[str, Any]], verb: str) -> dict[int, Item]:
    """Each item once, each Active. Errors name the line at fault (`lines[i].item_id`)."""
    seen: set[int] = set()
    for i, line in enumerate(lines):
        if line["item_id"] in seen:
            raise ApiError(400, "validation_error", "Each item can appear once.", f"lines[{i}].item_id")
        seen.add(line["item_id"])
    items = {i.pk: i for i in Item.objects.filter(pk__in=seen)}
    for i, line in enumerate(lines):
        item = items.get(line["item_id"])
        if item is None:
            raise ApiError(400, "validation_error", "This item does not exist.", f"lines[{i}].item_id")
        if item.status != ItemStatus.ACTIVE:
            raise ApiError(
                400, "validation_error", f"Only Active items can be {verb}.", f"lines[{i}].item_id"
            )
    return items


def _fold_average_cost(item: Item, quantity: int, unit_cost: Decimal) -> None:
    """Weighted average over everything on hand at every location (OQ-16), stored at 4 dp.

    The ItemCost row is locked first, so two receipts of one item cannot both read the same old average.
    """
    row, created = ItemCost.objects.get_or_create(item=item, defaults={"average_cost": unit_cost})
    # shortcut: no stock exists without an ItemCost row today (only receipts, seed_dev add stock);
    # the CSV opening-stock import must create the cost row first, or fold stock held elsewhere (OQ-30).
    if created:
        return
    row = ItemCost.objects.select_for_update().get(pk=item.pk)
    on_hand = StockBalance.objects.filter(item=item).aggregate(total=Sum("on_hand"))["total"] or 0
    if on_hand <= 0:
        average = unit_cost
    else:
        average = (row.average_cost * on_hand + unit_cost * quantity) / (on_hand + quantity)
    row.average_cost = average.quantize(FOUR_DP, rounding=ROUND_HALF_UP)
    row.save(update_fields=["average_cost", "updated_at"])


def create_receipt(
    request: HttpRequest, actor: User, data: dict[str, Any], operation_id: uuid.UUID
) -> GoodsReceipt:
    require_action(actor, "goods_receipts.manage")
    warehouse = active_warehouse()
    require_location(actor, warehouse, request.session)
    lines: list[dict[str, Any]] = data["lines"]
    items = active_items(lines, "received")
    role = active_role(actor) or ""
    with transaction.atomic():
        receipt = GoodsReceipt.objects.create(
            reference=uuid.uuid4().hex[:20],  # replaced below, once the id exists
            location=warehouse,
            supplier_name=data["supplier_name"],
            notes=data.get("notes", ""),
            received_by=actor,
            operation_id=operation_id,
        )
        receipt.reference = f"GRN-{receipt.pk:06d}"
        receipt.save(update_fields=["reference"])
        rows = GoodsReceiptLine.objects.bulk_create(
            [
                GoodsReceiptLine(
                    receipt=receipt,
                    item=items[ln["item_id"]],
                    quantity=ln["quantity"],
                    unit_cost=ln["unit_cost"],
                )
                for ln in lines
            ]
        )
        for row in sorted(rows, key=lambda r: r.item_id):  # fixed lock order between concurrent receipts
            _fold_average_cost(row.item, row.quantity, row.unit_cost)
        post_stock_changes(
            [
                StockChange(
                    location=warehouse,
                    item=row.item,
                    bucket=Bucket.ON_HAND,
                    delta=row.quantity,
                    movement_type=MovementType.SUPPLIER_RECEIPT,
                    source_type=SourceType.GOODS_RECEIPT,
                    source_id=receipt.pk,
                    source_line_id=row.pk,
                    source_ref=receipt.reference,
                )
                for row in rows
            ],
            actor=actor,
            actor_role=role,
            actor_location=warehouse,
            operation_id=operation_id,
            note=data.get("notes", ""),
            audit_action="stock_posted",
        )
        record_event(
            "goods_receipt_confirmed",
            request=request,
            actor=actor,
            actor_role=role,
            location=warehouse,
            target_type="goods_receipt",
            target_ref=receipt.reference,
            after={"supplier_name": receipt.supplier_name, "lines": len(rows)},  # no cost in the audit trail
            operation_id=operation_id,
        )
    return receipt

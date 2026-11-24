"""Sales (B6.1) and sale cancellation (B6.5). Stock moves only through `post_stock_changes`.

Record: sale, lines, ledger rows (on_hand -q) and audit rows commit together or not at all. Cancel: a linked
reversal (ledger rows with `reverses_movement`), the status moves to Cancelled, the original stays visible.
Audit events: sale_recorded, sale_cancelled (plus the stock service's stock_posted).
"""

import uuid
from decimal import Decimal
from typing import Any

from django.db import transaction
from django.db.models import QuerySet
from django.http import HttpRequest

from accounts.me import working_branch
from accounts.models import User
from audit.services import record_event
from branches.models import LocationKind
from config.errors import ApiError
from inventory.models import ItemCost, ItemPrice
from roles import constants as c
from roles.permissions import require_action, require_location
from roles.services import active_role
from sales.models import PaymentMethod, Sale, SaleCancellation, SaleLine, SaleStatus
from stock_ledger.models import Bucket, MovementType, SourceType, StockMovement
from stock_ledger.services import StockChange, post_stock_changes
from warehouse.services import active_items

MAX_TOTAL = Decimal(10) ** 10


def sale_queryset() -> QuerySet[Sale]:
    return Sale.objects.select_related(
        "location", "staff", "payment_method", "cancellation__cancelled_by"
    ).prefetch_related("lines__item")


def record_sale(request: HttpRequest, actor: User, data: dict[str, Any], operation_id: uuid.UUID) -> Sale:
    """Sell in the caller's working branch at the price list price; blocked when stock is short.

    Rules: only Active items with a selling price (OQ-21); one line per item; quantity at most the
    available stock (409 insufficient_stock, nothing is written); the price is never taken from the client.
    """
    require_action(actor, "sales.record")
    location = working_branch(actor, request)
    if location is None:
        raise ApiError(403, "wrong_branch", "Choose a working branch first.")
    if location.kind != LocationKind.BRANCH:
        raise ApiError(403, "wrong_branch", "Sales are recorded in a branch.")
    require_location(actor, location, request.session)
    method = PaymentMethod.objects.filter(code=data["payment_method"], is_active=True).first()
    if method is None:
        raise ApiError(400, "validation_error", "Choose a payment method.", "payment_method")
    lines: list[dict[str, Any]] = data["lines"]
    items = active_items(lines, "sold")
    prices = dict(ItemPrice.objects.filter(item__in=items.values()).values_list("item_id", "selling_price"))
    for i, line in enumerate(lines):
        if line["item_id"] not in prices:
            raise ApiError(
                400,
                "validation_error",
                f"{items[line['item_id']].name} has no selling price yet, so it cannot be sold.",
                f"lines[{i}].item_id",
            )
    role = active_role(actor) or ""
    total = sum((prices[ln["item_id"]] * ln["quantity"] for ln in lines), Decimal("0.00"))
    if total >= MAX_TOTAL:  # the column holds 10 integer digits
        raise ApiError(400, "validation_error", "The sale total is too large.", "lines")
    with transaction.atomic():
        # Read the cost under the row lock, in item order like a receipt: the snapshot is never stale.
        costs = dict(
            ItemCost.objects.select_for_update()
            .filter(item__in=items.values())
            .order_by("item_id")
            .values_list("item_id", "average_cost")
        )
        sale = Sale.objects.create(
            reference=uuid.uuid4().hex[:20],  # replaced below, once the id exists
            location=location,
            staff=actor,
            payment_method=method,
            total=total,
            operation_id=operation_id,
        )
        sale.reference = f"SAL-{sale.pk:06d}"
        sale.save(update_fields=["reference"])
        rows = SaleLine.objects.bulk_create(
            [
                SaleLine(
                    sale=sale,
                    item=items[ln["item_id"]],
                    quantity=ln["quantity"],
                    unit_price=prices[ln["item_id"]],
                    line_total=prices[ln["item_id"]] * ln["quantity"],
                    unit_cost_snapshot=costs.get(ln["item_id"], Decimal("0")),  # 4 dp, never in the API
                )
                for ln in lines
            ]
        )
        post_stock_changes(
            [
                StockChange(
                    location=location,
                    item=row.item,
                    bucket=Bucket.ON_HAND,
                    delta=-row.quantity,
                    movement_type=MovementType.SALE,
                    source_type=SourceType.SALE,
                    source_id=sale.pk,
                    source_line_id=row.pk,
                    source_ref=sale.reference,
                )
                for row in rows
            ],
            actor=actor,
            actor_role=role,
            actor_location=location,
            operation_id=operation_id,
        )
        record_event(
            "sale_recorded",
            request=request,
            actor=actor,
            actor_role=role,
            location=location,
            target_type="sale",
            target_ref=sale.reference,
            after={"lines": len(rows), "total": str(total), "payment_method": method.code},
            operation_id=operation_id,
        )
    return sale


def cancel_sale(
    request: HttpRequest, actor: User, sale_id: int, reason: str, operation_id: uuid.UUID
) -> Sale:
    """Super Admin, or the Branch Admin of the sale's branch, cancels a Completed sale with a reason.

    Rules: reason required; a second cancel is 409; the stock comes back through the stock service as
    reversal rows linked to the original ledger rows. Audit event: sale_cancelled.
    """
    require_action(actor, "sales.cancel")  # SA and BA (row 39)
    role = active_role(actor) or ""
    reason = reason.strip()
    if not reason:
        raise ApiError(400, "validation_error", "Say why the sale is cancelled.", "reason")
    with transaction.atomic():
        sale = Sale.objects.select_for_update().select_related("location").filter(pk=sale_id).first()
        if sale is None or (role == c.BRANCH_ADMIN and sale.location_id != actor.permanent_location_id):
            raise ApiError(404, "not_found", "No such sale.")
        require_location(actor, sale.location, request.session)
        if sale.status != SaleStatus.COMPLETED:
            raise ApiError(409, "conflict", f"This sale is already {sale.status}.")
        originals = list(
            StockMovement.objects.select_related("item").filter(
                source_type=SourceType.SALE, source_id=sale.pk, movement_type=MovementType.SALE
            )
        )
        cancellation = SaleCancellation.objects.create(
            sale=sale,
            reason=reason,
            cancelled_by=actor,
            cancelled_role=role,
            operation_id=operation_id,
        )
        post_stock_changes(
            [
                StockChange(
                    location=sale.location,
                    item=row.item,
                    bucket=Bucket.ON_HAND,
                    delta=-row.quantity_delta,
                    movement_type=MovementType.SALE_CANCELLATION,
                    source_type=SourceType.SALE_CANCELLATION,
                    source_id=cancellation.pk,
                    source_line_id=row.source_line_id,
                    source_ref=sale.reference,
                    reverses_movement_id=row.pk,
                )
                for row in originals
            ],
            actor=actor,
            actor_role=role,
            actor_location=sale.location,
            operation_id=operation_id,
            note=reason,
        )
        sale.status = SaleStatus.CANCELLED
        sale.save(update_fields=["status"])
        record_event(
            "sale_cancelled",
            request=request,
            actor=actor,
            actor_role=role,
            location=sale.location,
            target_type="sale",
            target_ref=sale.reference,
            before={"status": SaleStatus.COMPLETED},
            after={"status": SaleStatus.CANCELLED, "reason": reason},
            operation_id=operation_id,
        )
    return sale

"""Dispatch and branch receiving (B5.2, B5.3). Stock moves only through `post_stock_changes`.

Dispatch: origin reserved +q. Receipt of accepted a: origin reserved -a and on_hand -a, destination
on_hand +a. Rejected or short quantity stays reserved at the origin as an open discrepancy (ERD s6).
"""

import uuid
from typing import Any

from django.db import transaction
from django.db.models import QuerySet
from django.http import HttpRequest
from django.utils import timezone

from accounts.models import User
from audit.services import record_event
from branches.models import Location, LocationKind
from config.errors import ApiError
from roles.permissions import can_act_in, require_action, require_location
from roles.services import active_role
from stock_ledger.models import Bucket, MovementType, SourceType
from stock_ledger.services import StockChange, post_stock_changes
from transfers.models import Dispatch, DispatchLine, DispatchStatus
from warehouse.services import active_items, active_warehouse


def dispatch_queryset() -> QuerySet[Dispatch]:
    return Dispatch.objects.select_related(
        "origin_location", "destination_location", "dispatched_by", "received_by"
    ).prefetch_related("lines__item", "lines__resolutions")


def create_dispatch(
    request: HttpRequest, actor: User, data: dict[str, Any], operation_id: uuid.UUID
) -> Dispatch:
    require_action(actor, "dispatches.create")
    origin = active_warehouse()
    require_location(actor, origin, request.session)
    destination = Location.objects.filter(
        pk=data["destination_id"], kind=LocationKind.BRANCH, is_active=True
    ).first()
    if destination is None:
        raise ApiError(400, "validation_error", "Choose an active branch.", "destination_id")
    lines: list[dict[str, Any]] = data["lines"]
    items = active_items(lines, "dispatched")
    role = active_role(actor) or ""
    with transaction.atomic():
        dispatch = Dispatch.objects.create(
            reference=uuid.uuid4().hex[:20],  # replaced below, once the id exists
            origin_location=origin,
            destination_location=destination,
            dispatched_by=actor,
            operation_id=operation_id,
        )
        dispatch.reference = f"TRF-{dispatch.pk:06d}"
        dispatch.save(update_fields=["reference"])
        rows = DispatchLine.objects.bulk_create(
            [
                DispatchLine(dispatch=dispatch, item=items[ln["item_id"]], qty_sent=ln["quantity"])
                for ln in lines
            ]
        )
        post_stock_changes(
            [
                StockChange(
                    location=origin,
                    item=row.item,
                    bucket=Bucket.RESERVED,
                    delta=row.qty_sent,
                    movement_type=MovementType.DISPATCH,
                    source_type=SourceType.DISPATCH,
                    source_id=dispatch.pk,
                    source_line_id=row.pk,
                    source_ref=dispatch.reference,
                )
                for row in rows
            ],
            actor=actor,
            actor_role=role,
            actor_location=origin,
            operation_id=operation_id,
        )
        record_event(
            "dispatch_created",
            request=request,
            actor=actor,
            actor_role=role,
            location=origin,
            target_type="dispatch",
            target_ref=dispatch.reference,
            after={"destination": destination.code, "lines": len(rows)},
            operation_id=operation_id,
        )
    return dispatch


def _decide(
    dispatch: Dispatch, data: dict[str, Any]
) -> tuple[str, dict[int, tuple[int, int, int, str]], str]:
    """Validate the decision; returns (status, {line_id: (received, accepted, rejected, note)}, note)."""
    decision = data["decision"]
    lines = {ln.pk: ln for ln in dispatch.lines.all()}
    if decision == "reject":
        reason = data.get("reason", "").strip()
        if not reason:
            raise ApiError(400, "validation_error", "Say why the dispatch is rejected.", "reason")
        # Nothing is credited; the whole quantity stays reserved at the sender as a discrepancy.
        return (
            DispatchStatus.REJECTED,
            {i: (ln.qty_sent, 0, ln.qty_sent, "") for i, ln in lines.items()},
            reason,
        )
    note = data.get("note", "").strip()
    if decision == "approve_partial" and not note:
        raise ApiError(400, "validation_error", "Add a note for a partial receipt.", "note")
    sent = data.get("lines") or []
    if sorted(s["line_id"] for s in sent) != sorted(lines):
        raise ApiError(400, "validation_error", "Give every dispatch line exactly once.", "lines")
    decided: dict[int, tuple[int, int, int, str]] = {}
    for i, entry in enumerate(sent):
        line = lines[entry["line_id"]]
        received, accepted = entry["qty_received"], entry["qty_accepted"]
        if received > line.qty_sent:
            raise ApiError(400, "validation_error", "More arrived than was sent.", f"lines[{i}].qty_received")
        if accepted > received:
            raise ApiError(
                400, "validation_error", "Accepted cannot exceed received.", f"lines[{i}].qty_accepted"
            )
        if decision == "approve_all" and (received != line.qty_sent or accepted != line.qty_sent):
            raise ApiError(
                400, "validation_error", "Approve all needs every line in full.", f"lines[{i}].qty_accepted"
            )
        decided[line.pk] = (received, accepted, received - accepted, entry.get("line_note", ""))
    status = DispatchStatus.COMPLETED if decision == "approve_all" else DispatchStatus.PARTIALLY_RECEIVED
    return status, decided, note


def receive_dispatch(
    request: HttpRequest, actor: User, dispatch_id: int, data: dict[str, Any], operation_id: uuid.UUID
) -> Dispatch:
    require_action(actor, "dispatches.receive")
    role = active_role(actor) or ""
    with transaction.atomic():
        dispatch = (
            Dispatch.objects.select_for_update(of=("self",))
            .select_related("origin_location", "destination_location")
            .prefetch_related("lines__item")
            .filter(pk=dispatch_id)
            .first()
        )
        if dispatch is None:
            raise ApiError(404, "not_found", "Not found.")
        destination = dispatch.destination_location
        if not can_act_in(actor, destination, request.session):  # destination only; else 404 (OQ-30)
            raise ApiError(404, "not_found", "Not found.")
        if dispatch.status != DispatchStatus.IN_TRANSIT:
            raise ApiError(409, "conflict", "This dispatch already has a receiving decision.")
        status, decided, note = _decide(dispatch, data)
        changes: list[StockChange] = []
        for line in dispatch.lines.all():
            received, accepted, rejected, line_note = decided[line.pk]
            line.qty_received, line.qty_accepted, line.qty_rejected = received, accepted, rejected
            line.line_note = line_note
            line.save(update_fields=["qty_received", "qty_accepted", "qty_rejected", "line_note"])
            if accepted:
                for location, bucket, delta in (
                    (dispatch.origin_location, Bucket.RESERVED, -accepted),
                    (dispatch.origin_location, Bucket.ON_HAND, -accepted),
                    (destination, Bucket.ON_HAND, accepted),
                ):
                    changes.append(
                        StockChange(
                            location=location,
                            item=line.item,
                            bucket=bucket,
                            delta=delta,
                            movement_type=MovementType.DISPATCH_RECEIPT,
                            source_type=SourceType.DISPATCH,
                            source_id=dispatch.pk,
                            source_line_id=line.pk,
                            source_ref=dispatch.reference,
                        )
                    )
        dispatch.status = status
        dispatch.received_at = timezone.now()
        dispatch.received_by = actor
        dispatch.receive_note = note
        dispatch.save(update_fields=["status", "received_at", "received_by", "receive_note"])
        if changes:
            post_stock_changes(
                changes,
                actor=actor,
                actor_role=role,
                actor_location=destination,
                operation_id=operation_id,
                note=note,
            )
        record_event(
            "dispatch_rejected" if status == DispatchStatus.REJECTED else "dispatch_received",
            request=request,
            actor=actor,
            actor_role=role,
            location=destination,
            target_type="dispatch",
            target_ref=dispatch.reference,
            before={"status": DispatchStatus.IN_TRANSIT},
            after={
                "status": status,
                "accepted": sum(d[1] for d in decided.values()),
                "shortfall": sum(ln.qty_sent - decided[ln.pk][1] for ln in dispatch.lines.all()),
            },
            operation_id=operation_id,
        )
    return dispatch

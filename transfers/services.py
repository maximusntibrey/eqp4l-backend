"""Dispatch and branch receiving (B5.2, B5.3). Stock moves only through `post_stock_changes`.

Dispatch: origin reserved +q. Receipt of accepted a: origin reserved -a and on_hand -a, destination
on_hand +a. Rejected or short quantity stays reserved at the origin as an open discrepancy (ERD s6).
"""

import uuid
from typing import Any, cast

from django.db import connection, transaction
from django.db.models import F, QuerySet
from django.http import HttpRequest
from django.utils import timezone

from accounts.models import User
from audit.services import record_event
from branches.models import Location, LocationKind
from config.errors import ApiError
from roles import constants as c
from roles.permissions import can_act_in, require_action, require_location, working_location_id
from roles.services import active_role
from stock_ledger.models import Bucket, MovementType, SourceType
from stock_ledger.services import StockChange, post_stock_changes
from transfers.models import Dispatch, DispatchLine, DispatchResolution, DispatchStatus, ResolutionAction
from warehouse.services import active_items, active_warehouse

# action -> (movement type, [(side, bucket, sign)]); side "origin" or "destination". DEC 2026-11-18.
_EFFECTS: dict[str, tuple[str, list[tuple[str, str, int]]]] = {
    ResolutionAction.RETURN_TO_SENDER: (MovementType.RESOLUTION_RETURN, [("origin", Bucket.RESERVED, -1)]),
    ResolutionAction.CONFIRM_LOSS: (
        MovementType.RESOLUTION_LOSS,
        [("origin", Bucket.RESERVED, -1), ("origin", Bucket.ON_HAND, -1)],
    ),
    ResolutionAction.RECORD_DAMAGE: (
        MovementType.RESOLUTION_DAMAGE,
        [
            ("origin", Bucket.RESERVED, -1),
            ("origin", Bucket.ON_HAND, -1),
            ("destination", Bucket.QUARANTINED, 1),
        ],
    ),
}


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


# A deactivated location keeps its shortfalls resolvable: stranded reserved stock must be cleanable (FIX-49).
def shortfall_lines(actor: User, session: Any) -> QuerySet[DispatchLine]:
    """Received lines with a shortfall that the actor may see (rows 33, 34)."""
    qs = DispatchLine.objects.select_related(
        "item", "dispatch__origin_location", "dispatch__destination_location", "dispatch__received_by"
    ).prefetch_related("resolutions__resolved_by")
    qs = qs.filter(qty_accepted__isnull=False, qty_sent__gt=F("qty_accepted"))
    role = active_role(actor)
    if role == c.SUPER_ADMIN:
        return qs
    own = working_location_id(actor, session)
    if own is None or role not in (c.WAREHOUSE_ADMIN, c.BRANCH_ADMIN):
        return qs.none()
    side = (
        "dispatch__origin_location_id" if role == c.WAREHOUSE_ADMIN else "dispatch__destination_location_id"
    )
    return qs.filter(**{side: own})


def resolve_shortfall(
    request: HttpRequest, actor: User, line_id: int, data: dict[str, Any], operation_id: uuid.UUID
) -> DispatchLine:
    """Resolve part or all of one line's open shortfall through the stock service (B7.3, rows 34, 35)."""
    require_action(actor, "shortfalls.resolve")
    note = data["note"].strip()
    if not note:
        raise ApiError(400, "validation_error", "Say why, in a note.", "note")
    action, quantity = data["resolution"], data["quantity"]
    role = active_role(actor) or ""
    with transaction.atomic():
        # Out of scope is 404, like a missing id. The row lock serialises two resolvers of one line.
        visible = shortfall_lines(actor, request.session).filter(pk=line_id).values_list("pk", flat=True)
        line = (
            DispatchLine.objects.select_for_update(of=("self",))
            .select_related("item", "dispatch__origin_location", "dispatch__destination_location")
            .filter(pk__in=list(visible))
            .first()
        )
        if line is None:
            raise ApiError(404, "not_found", "Not found.")
        accepted = cast(int, line.qty_accepted)  # shortfall_lines only returns received lines
        resolved = sum(line.resolutions.values_list("quantity", flat=True))
        remaining = line.qty_sent - accepted - resolved
        if remaining <= 0:
            raise ApiError(409, "conflict", "This shortfall is already fully resolved.")
        if quantity > remaining:
            raise ApiError(400, "validation_error", f"Only {remaining} left to resolve.", "quantity")
        dispatch = line.dispatch
        origin, destination = dispatch.origin_location, dispatch.destination_location
        with connection.cursor() as cursor:  # append-only row: take the id first, so the reference is final
            cursor.execute("SELECT nextval(pg_get_serial_sequence('transfers_dispatchresolution', 'id'))")
            new_id = int(cursor.fetchone()[0])
        resolution = DispatchResolution.objects.create(
            id=new_id,
            reference=f"RES-{new_id:06d}",
            dispatch_line=line,
            action=action,
            quantity=quantity,
            note=note,
            resolved_by=actor,
            resolved_role=role,
            is_self_approval=dispatch.received_by_id == actor.pk,  # OQ-9c: flagged, allowed
            operation_id=operation_id,
        )
        movement_type, effects = _EFFECTS[action]
        post_stock_changes(
            [
                StockChange(
                    location=origin if side == "origin" else destination,
                    item=line.item,
                    bucket=bucket,
                    delta=sign * quantity,
                    movement_type=movement_type,
                    source_type=SourceType.DISPATCH_RESOLUTION,
                    source_id=resolution.pk,
                    source_line_id=line.pk,
                    source_ref=dispatch.reference,
                )
                for side, bucket, sign in effects
            ],
            actor=actor,
            actor_role=role,
            actor_location=origin if role == c.WAREHOUSE_ADMIN else destination,
            operation_id=operation_id,
            note=note,
            audit_action="shortfall_stock_posted",
        )
        record_event(
            "shortfall_resolved",
            request=request,
            actor=actor,
            actor_role=role,
            location=origin if role == c.WAREHOUSE_ADMIN else destination,
            target_type="dispatch",
            target_ref=dispatch.reference,
            before={"remaining": remaining},
            after={
                "action": action,
                "quantity": quantity,
                "remaining": remaining - quantity,
                "line_id": line.pk,
            },
            is_self_approval=resolution.is_self_approval,
            operation_id=operation_id,
        )
    return line

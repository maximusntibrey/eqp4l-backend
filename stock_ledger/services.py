"""The stock service: the only code that writes stock_balances and stock_movements (ERD s4, TASKS 0.3).

B2.5 ships the minimal posting path (`post_stock_changes`): atomic, rows locked in ascending
(location_id, item_id) order, balances validated, one ledger row per bucket changed and one audit
row, all in one transaction. B4.3 builds the typed events (receipt, dispatch, sale, ...) and the
idempotency-key lookup on this same entry point; nothing else may touch balances or the ledger.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from django.db import IntegrityError, connection, transaction

from accounts.models import User
from audit.services import record_event
from branches.models import Location
from config.errors import ApiError
from inventory.models import Item, StockBalance
from stock_ledger.models import Bucket, MovementType, SourceType, StockMovement


@dataclass(frozen=True)
class StockChange:
    """One bucket change at one location. `delta` is signed and never zero."""

    location: Location
    item: Item
    bucket: str
    delta: int
    movement_type: str
    source_type: str
    source_id: int
    source_line_id: int
    source_ref: str = ""
    reverses_movement_id: int | None = None  # a reversal row links to the ledger row it compensates


def _lock_balances(changes: Sequence[StockChange]) -> dict[tuple[int, int], StockBalance]:
    keys = sorted({(ch.location.pk, ch.item.pk) for ch in changes})
    StockBalance.objects.bulk_create(
        [StockBalance(location_id=loc, item_id=item) for loc, item in keys], ignore_conflicts=True
    )
    locked: dict[tuple[int, int], StockBalance] = {}
    for loc, item in keys:  # fixed order avoids deadlocks between concurrent operations
        locked[(loc, item)] = StockBalance.objects.select_for_update().get(location_id=loc, item_id=item)
    return locked


def _signature(rows: Sequence[Any]) -> list[tuple[Any, ...]]:
    """What an operation did, comparable between requested changes and stored ledger rows."""

    def key(r: Any) -> tuple[Any, ...]:
        loc, item = (r.location.pk, r.item.pk) if isinstance(r, StockChange) else (r.location_id, r.item_id)
        delta = r.delta if isinstance(r, StockChange) else r.quantity_delta
        return (loc, item, r.bucket, delta, r.movement_type, r.source_type, r.source_id, r.source_line_id)

    return sorted(key(r) for r in rows)


def post_stock_changes(
    changes: Sequence[StockChange],
    *,
    actor: User | None,
    actor_role: str = "",
    actor_location: Location | None = None,
    operation_id: uuid.UUID | None = None,
    note: str = "",
    audit_action: str = "stock_posted",
) -> list[StockMovement]:
    """Apply `changes` atomically and write the ledger rows plus one audit event.

    Rules: no bucket goes negative and reserved never exceeds on_hand (409 insufficient_stock naming the
    item and location); a source line can never post twice (409 conflict).
    Audit event: `audit_action`.

    Idempotency: pass the operation's `operation_id` (derived from the request's Idempotency-Key). Posting the
    same operation again with the same changes returns the stored rows and writes nothing; the same id with
    different changes is 409 `idempotency_conflict`. The lookup runs under the balance locks, so two
    concurrent copies cannot both post.
    """
    if not changes:
        raise ApiError(400, "validation_error", "Nothing to post.")
    if any(ch.delta == 0 or ch.bucket not in Bucket.values for ch in changes):
        raise ApiError(400, "validation_error", "Each stock change needs a bucket and a non-zero quantity.")
    replayable = operation_id is not None
    operation_id = operation_id or uuid.uuid4()
    with transaction.atomic():
        if replayable:
            # Serialise copies of one operation even when they touch different balance rows.
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", [str(operation_id)])
        balances = _lock_balances(changes)
        if replayable:
            stored = list(StockMovement.objects.filter(operation_id=operation_id).order_by("id"))
            if stored:
                if _signature(stored) != _signature(changes):
                    raise ApiError(
                        409, "idempotency_conflict", "This operation ID was already used for other changes."
                    )
                return stored
        rows: list[StockMovement] = []
        for ch in changes:
            balance = balances[(ch.location.pk, ch.item.pk)]
            after = getattr(balance, ch.bucket) + ch.delta
            if (
                after < 0
            ):  # every step, not just the final balance: the ledger refuses a negative balance_after
                raise ApiError(
                    409,
                    "insufficient_stock",
                    f"Not enough stock of {ch.item.name} at {ch.location.name}.",
                )
            setattr(balance, ch.bucket, after)
            rows.append(
                StockMovement(
                    location=ch.location,
                    item=ch.item,
                    bucket=ch.bucket,
                    quantity_delta=ch.delta,
                    balance_after=after,
                    movement_type=ch.movement_type,
                    source_type=ch.source_type,
                    source_id=ch.source_id,
                    source_ref=ch.source_ref,
                    source_line_id=ch.source_line_id,
                    operation_id=operation_id,
                    actor=actor,
                    actor_role=actor_role,
                    actor_location=actor_location,
                    note=note,
                    reverses_movement_id=ch.reverses_movement_id,
                )
            )
        for key, balance in balances.items():
            if (
                balance.on_hand < 0
                or balance.reserved < 0
                or balance.quarantined < 0
                or balance.reserved > balance.on_hand
            ):
                change = next(c for c in changes if (c.location.pk, c.item.pk) == key)
                raise ApiError(
                    409,
                    "insufficient_stock",
                    f"Not enough stock of {change.item.name} at {change.location.name}.",
                )
            balance.save(update_fields=["on_hand", "reserved", "quarantined", "updated_at"])
        try:
            with transaction.atomic():
                StockMovement.objects.bulk_create(rows)
        except IntegrityError as exc:  # only movements_no_double_post can remain: balances were checked above
            raise ApiError(409, "conflict", "This stock change has already been posted.") from exc
        record_event(
            audit_action,
            actor=actor,
            actor_role=actor_role,
            location=actor_location,
            target_type="stock",
            target_ref=str(operation_id),
            after={"rows": len(rows), "movement_types": sorted({r.movement_type for r in rows})},
            operation_id=operation_id,
        )
    return rows


__all__ = ["MovementType", "SourceType", "StockChange", "post_stock_changes"]

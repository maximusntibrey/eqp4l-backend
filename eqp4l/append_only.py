"""Append-only guards for the stock ledger and the audit log (ERD s7).

Layers 1 and 2 (model and queryset) live here. Layer 3 (database triggers that reject
UPDATE, DELETE and TRUNCATE for every role) is plain SQL written out in the migrations
``stock_ledger/0002`` and ``audit/0002``; they do not import this module, so changing it can
never alter what a historical migration does.
"""

from typing import Any, NoReturn

from django.db import models


class AppendOnlyError(Exception):
    """Raised when code tries to change or delete a row of an append-only table."""


def _refuse(action: str) -> NoReturn:
    raise AppendOnlyError(f"{action} is not allowed: this table is append-only.")


class AppendOnlyQuerySet(models.QuerySet[Any]):
    """Only ``create()`` and ``bulk_create()`` exist; every other write raises."""

    def update(self, **kwargs: Any) -> NoReturn:
        _refuse("update()")

    def delete(self) -> NoReturn:
        _refuse("delete()")

    def bulk_update(self, objs: Any, fields: Any, batch_size: Any = None) -> NoReturn:
        _refuse("bulk_update()")

    def bulk_create(self, objs: Any, *args: Any, **kwargs: Any) -> Any:
        if kwargs.get("update_conflicts"):
            _refuse("bulk_create(update_conflicts=True)")
        return super().bulk_create(objs, *args, **kwargs)


class AppendOnlyModel(models.Model):
    """An existing row can never be saved again or deleted (ERD s7 layer 1)."""

    objects = AppendOnlyQuerySet.as_manager()

    class Meta:
        abstract = True

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self._state.adding:
            _refuse("Changing an existing row")
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> NoReturn:
        _refuse("delete()")

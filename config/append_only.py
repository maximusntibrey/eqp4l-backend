"""Layer 1 of the append-only rule (ERD s4): rows of ledger-type tables can be inserted, never changed.

Layer 2 is the database trigger in each app's migration; layer 3 is the role grants applied by
`manage.py lock_append_only_tables`.
"""

from typing import Any

from django.db import models


class AppendOnlyError(RuntimeError):
    """Raised when code tries to change or remove a row of an append-only table."""


class AppendOnlyQuerySet(models.QuerySet["AppendOnlyModel"]):
    def update(self, **kwargs: Any) -> int:
        raise AppendOnlyError(f"{self.model._meta.db_table} is append-only: update is not allowed")

    def bulk_update(self, objs: Any, fields: Any, batch_size: int | None = None) -> int:
        raise AppendOnlyError(f"{self.model._meta.db_table} is append-only: update is not allowed")

    def delete(self) -> tuple[int, dict[str, int]]:
        raise AppendOnlyError(f"{self.model._meta.db_table} is append-only: delete is not allowed")


class AppendOnlyModel(models.Model):
    objects = AppendOnlyQuerySet.as_manager()

    class Meta:
        abstract = True

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self._state.adding:
            raise AppendOnlyError(f"{self._meta.db_table} is append-only: existing rows cannot be saved")
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        raise AppendOnlyError(f"{self._meta.db_table} is append-only: delete is not allowed")

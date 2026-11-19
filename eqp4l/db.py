"""Shared model building blocks: the audit fields of editable records (ERD s2)."""

from django.conf import settings
from django.db import models


class AuditFields(models.Model):
    """``created_at``, ``created_by``, ``updated_at``, ``updated_by`` (BE s3.2; ERD s2).

    The two user columns are required (NOT NULL). Only ``accounts.User`` overrides them as
    nullable, because the first user (SA-0001) is seeded (ERD s3.1).
    """

    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        editable=False,
        on_delete=models.PROTECT,
        related_name="+",
    )
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        editable=False,
        on_delete=models.PROTECT,
        related_name="+",
    )

    class Meta:
        abstract = True

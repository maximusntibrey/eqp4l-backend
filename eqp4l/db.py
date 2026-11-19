"""Shared model building blocks: the audit fields of editable records (ERD s2)."""

from django.conf import settings
from django.db import models


class AuditFields(models.Model):
    """``created_at``, ``created_by``, ``updated_at``, ``updated_by`` (BE s3.2; ERD s2).

    The two user columns are nullable only so that rows created by a data migration or the
    seed (no signed-in actor) are possible; the services always set them.
    """

    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        editable=False,
        on_delete=models.PROTECT,
        related_name="+",
    )
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        editable=False,
        on_delete=models.PROTECT,
        related_name="+",
    )

    class Meta:
        abstract = True

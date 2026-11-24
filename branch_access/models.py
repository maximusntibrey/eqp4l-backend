from django.conf import settings
from django.db import models

from config.append_only import AppendOnlyModel


class SwitchLog(AppendOnlyModel):
    """Every working-branch switch (role switch columns come with Sprint 5)."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    from_location = models.ForeignKey(
        "branches.Location", null=True, on_delete=models.PROTECT, related_name="+"
    )
    to_location = models.ForeignKey("branches.Location", on_delete=models.PROTECT, related_name="+")
    at = models.DateTimeField(auto_now_add=True)

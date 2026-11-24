"""Small helpers shared by the model modules."""

from django.db import models


def choice_check(field: str, choices: type[models.TextChoices], name: str) -> models.CheckConstraint:
    """Database CHECK that a text column holds one of the allowed codes (NULL passes)."""
    return models.CheckConstraint(condition=models.Q(**{f"{field}__in": list(choices.values)}), name=name)

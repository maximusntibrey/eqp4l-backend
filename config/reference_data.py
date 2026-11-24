"""Fixed reference rows, created after every migrate (and every test flush): roles, ID counters,
categories and payment methods. Idempotent get_or_create; business data (items, users) is not seeded here.
"""

from typing import Any

from django.apps import apps


def ensure_reference_data(using: str = "default", **kwargs: Any) -> None:
    from accounts.models import LoginIdSequence
    from inventory.catalog import SUBTYPES
    from inventory.models import Category, Subtype
    from roles.constants import ROLE_NAMES
    from roles.models import Role
    from sales.models import PaymentMethod

    if not apps.is_installed("accounts"):
        return
    for code, name in ROLE_NAMES.items():
        Role.objects.using(using).get_or_create(code=code, defaults={"name": name})
    for prefix in ("SA", "USR"):
        LoginIdSequence.objects.using(using).get_or_create(prefix=prefix)
    for name, subtypes in SUBTYPES.items():
        category, _ = Category.objects.using(using).get_or_create(name=name)
        for subtype in subtypes:
            Subtype.objects.using(using).get_or_create(category=category, name=subtype)
    for code, name in (("cash", "Cash"), ("mobile_money", "Mobile money"), ("card", "Card")):
        PaymentMethod.objects.using(using).get_or_create(code=code, defaults={"name": name})

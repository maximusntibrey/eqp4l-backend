"""Seed the payment methods: cash, mobile money, card (ERD s3.7; BE s6, configurable)."""

from django.db import migrations

METHODS = [("cash", "Cash"), ("mobile_money", "Mobile money"), ("card", "Card")]


def seed(apps, schema_editor):  # type: ignore[no-untyped-def]
    method = apps.get_model("sales", "PaymentMethod")
    for code, name in METHODS:
        method.objects.get_or_create(code=code, defaults={"name": name, "is_active": True})


class Migration(migrations.Migration):
    dependencies = [("sales", "0001_initial")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]

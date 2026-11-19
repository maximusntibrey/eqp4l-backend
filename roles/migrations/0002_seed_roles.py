"""Seed the four roles (ERD s3.2: ``roles_role`` is seeded by migration)."""

from django.db import migrations

ROLES = [
    ("super_admin", "Super Admin"),
    ("warehouse_admin", "Warehouse Admin"),
    ("branch_admin", "Branch Admin"),
    ("front_staff", "Front Staff"),
]


def seed(apps, schema_editor):  # type: ignore[no-untyped-def]
    role = apps.get_model("roles", "Role")
    for code, name in ROLES:
        role.objects.get_or_create(code=code, defaults={"name": name})


class Migration(migrations.Migration):
    dependencies = [("roles", "0001_initial")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]

from django.db import migrations


def add_role(apps, schema_editor):
    """Idempotent: post_migrate (config/reference_data.py) would also create the row."""
    apps.get_model("roles", "Role").objects.get_or_create(
        code="central_warehouse", defaults={"name": "Central Warehouse"}
    )


def remove_role(apps, schema_editor):
    """Reverse: refuse while any user holds the role, else drop the unused row."""
    Role = apps.get_model("roles", "Role")
    role = Role.objects.filter(code="central_warehouse").first()
    if role is None:
        return
    held = role.user_roles.count()
    if held:
        raise RuntimeError(f"Cannot reverse: {held} user(s) hold the central_warehouse role. Reassign them first.")
    role.delete()


class Migration(migrations.Migration):
    dependencies = [("roles", "0001_initial")]

    operations = [migrations.RunPython(add_role, remove_role)]

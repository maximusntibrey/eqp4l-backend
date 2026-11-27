from django.db import migrations


def _noop(apps, schema_editor):
    pass


def _refuse_if_several(apps, schema_editor):
    """Reverse guard: the one-warehouse constraint cannot return while several warehouses exist."""
    Location = apps.get_model("branches", "Location")
    count = Location.objects.filter(kind="warehouse").count()
    if count > 1:
        raise RuntimeError(
            f"Cannot reverse: {count} warehouses exist and the old rule allows one. "
            "Remove or convert the extra warehouses first."
        )


class Migration(migrations.Migration):
    dependencies = [("branches", "0001_initial")]

    operations = [
        migrations.RemoveConstraint(model_name="location", name="locations_one_warehouse"),
        # Runs first when reversing, so the refusal comes before the constraint is re-added.
        migrations.RunPython(_noop, _refuse_if_several),
    ]

"""Backstop for ERD s3.6: the resolutions of one discrepancy may not sum to more than its
``qty_short + qty_rejected``. The service checks this under the line lock first."""

from django.db import migrations

FUNCTION = """
CREATE FUNCTION transfers_resolution_sum_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    allowed numeric;
    used numeric;
BEGIN
    SELECT qty_short + qty_rejected INTO allowed
        FROM transfers_discrepancy WHERE id = NEW.discrepancy_id;
    SELECT COALESCE(SUM(quantity), 0) INTO used
        FROM transfers_discrepancyresolution WHERE discrepancy_id = NEW.discrepancy_id;
    IF used + NEW.quantity > allowed THEN
        RAISE EXCEPTION 'resolutions of discrepancy % exceed the flagged quantity', NEW.discrepancy_id
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$;
"""


class Migration(migrations.Migration):
    dependencies = [("transfers", "0001_initial")]
    operations = [
        migrations.RunSQL(
            [
                FUNCTION,
                "CREATE TRIGGER transfers_resolution_sum BEFORE INSERT ON "
                "transfers_discrepancyresolution FOR EACH ROW "
                "EXECUTE FUNCTION transfers_resolution_sum_guard();",
            ],
            [
                "DROP TRIGGER transfers_resolution_sum ON transfers_discrepancyresolution;",
                "DROP FUNCTION transfers_resolution_sum_guard();",
            ],
        )
    ]

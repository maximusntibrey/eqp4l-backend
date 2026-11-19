"""Make the resolution-sum backstop concurrency-safe (follow-up to 0002).

Two concurrent inserts would each see the old SUM and both pass. The parent discrepancy row
is now locked ``FOR UPDATE`` first, so the second insert waits and then sees the first.
"""

from django.db import migrations

LOCKING = """
CREATE OR REPLACE FUNCTION transfers_resolution_sum_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    allowed numeric;
    used numeric;
BEGIN
    SELECT qty_short + qty_rejected INTO allowed
        FROM transfers_discrepancy WHERE id = NEW.discrepancy_id FOR UPDATE;
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

PREVIOUS = """
CREATE OR REPLACE FUNCTION transfers_resolution_sum_guard() RETURNS trigger LANGUAGE plpgsql AS $$
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
    dependencies = [("transfers", "0002_resolution_sum_trigger")]
    operations = [migrations.RunSQL(LOCKING, PREVIOUS)]

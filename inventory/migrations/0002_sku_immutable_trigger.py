"""``inventory_item.sku`` is immutable once a ledger, receipt, dispatch or sale line uses the
item (ERD s3.4, s9). The service enforces it too; this trigger is the database backstop."""

from django.db import migrations

FUNCTION = """
CREATE FUNCTION inventory_item_sku_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.sku IS DISTINCT FROM OLD.sku AND (
        EXISTS (SELECT 1 FROM stock_ledger_entry WHERE item_id = OLD.id)
        OR EXISTS (SELECT 1 FROM warehouse_goodsreceiptline WHERE item_id = OLD.id)
        OR EXISTS (SELECT 1 FROM transfers_dispatchline WHERE item_id = OLD.id)
        OR EXISTS (SELECT 1 FROM sales_saleline WHERE item_id = OLD.id)
    ) THEN
        RAISE EXCEPTION 'sku of item % cannot change: the item is used in a transaction', OLD.id
            USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN NEW;
END;
$$;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("inventory", "0001_initial"),
        ("stock_ledger", "0001_initial"),
        ("warehouse", "0001_initial"),
        ("transfers", "0001_initial"),
        ("sales", "0001_initial"),
    ]
    operations = [
        migrations.RunSQL(
            [
                FUNCTION,
                "CREATE TRIGGER inventory_item_sku_immutable BEFORE UPDATE OF sku ON inventory_item "
                "FOR EACH ROW EXECUTE FUNCTION inventory_item_sku_guard();",
            ],
            [
                "DROP TRIGGER inventory_item_sku_immutable ON inventory_item;",
                "DROP FUNCTION inventory_item_sku_guard();",
            ],
        )
    ]

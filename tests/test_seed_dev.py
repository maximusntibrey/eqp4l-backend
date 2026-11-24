"""B2.5: seed_dev is idempotent, DEBUG-only, env-password-only and posts stock through the ledger."""

from io import StringIO
from typing import Any

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from accounts.models import User, UserStatus
from audit.models import AuditEvent
from branches.models import Location
from inventory.models import Item, ItemPrice, StockBalance
from stock_ledger.models import StockMovement

PASSWORDS = {
    "SA": "seed-test-pass-sa-1",
    "WA": "seed-test-pass-wa-1",
    "BA": "seed-test-pass-ba-1",
    "FS": "seed-test-pass-fs-1",
}

pytestmark = pytest.mark.django_db


@pytest.fixture
def seed_env(settings: Any) -> Any:
    settings.DEBUG = True
    settings.DEV_SEED_PASSWORDS = dict(PASSWORDS)
    return settings


def run_seed() -> str:
    out = StringIO()
    call_command("seed_dev", stdout=out)
    return out.getvalue()


def test_seed_creates_expected_rows(seed_env: Any) -> None:
    out = run_seed()
    assert "SA-0001 (SA)" in out and "seed_dev: done" in out
    assert Location.objects.count() == 4
    assert Item.objects.count() == 5 and ItemPrice.objects.count() == 5
    users = {u.login_id: u for u in User.objects.all()}
    assert set(users) == {"SA-0001", "USR-0001", "USR-0002", "USR-0003"}
    assert all(u.status == UserStatus.ACTIVE and not u.must_change_password for u in users.values())
    assert users["SA-0001"].check_password(PASSWORDS["SA"])
    assert StockMovement.objects.count() == 10  # one ledger row per opening line
    assert AuditEvent.objects.filter(action="opening_stock_imported").count() == 4
    assert StockBalance.objects.get(location__code="WH", item__sku="SKU-000001").on_hand == 20


def test_seed_is_idempotent(seed_env: Any) -> None:
    run_seed()
    counts = (User.objects.count(), StockMovement.objects.count(), AuditEvent.objects.count())
    balances = list(StockBalance.objects.order_by("id").values_list("on_hand", flat=True))
    run_seed()
    assert (User.objects.count(), StockMovement.objects.count(), AuditEvent.objects.count()) == counts
    assert list(StockBalance.objects.order_by("id").values_list("on_hand", flat=True)) == balances


def test_seed_refuses_when_debug_is_off(settings: Any) -> None:
    settings.DEBUG = False
    settings.DEV_SEED_PASSWORDS = dict(PASSWORDS)
    with pytest.raises(CommandError, match="DEBUG"):
        run_seed()
    assert not User.objects.exists()


def test_seed_needs_passwords_from_the_environment(seed_env: Any) -> None:
    seed_env.DEV_SEED_PASSWORDS = {**PASSWORDS, "WA": ""}
    with pytest.raises(CommandError, match="WA"):
        run_seed()
    assert not User.objects.exists()


def test_seed_rejects_a_short_password(seed_env: Any) -> None:
    seed_env.DEV_SEED_PASSWORDS = {**PASSWORDS, "FS": "short"}
    with pytest.raises(CommandError, match="FS"):
        run_seed()


def test_every_stocked_item_has_a_cost_row(seed_env: Any) -> None:
    """OQ-30: stock enters only via receipts (cost row first) and the seed (cost row with the item)."""
    from inventory.models import ItemCost

    run_seed()
    stocked = set(StockBalance.objects.values_list("item_id", flat=True))
    assert stocked and stocked <= set(ItemCost.objects.values_list("item_id", flat=True))

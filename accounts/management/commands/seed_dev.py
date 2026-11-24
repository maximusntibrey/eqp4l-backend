"""Idempotent local dev seed (B2.5). Refuses to run unless DEBUG is on. Re-running changes nothing.

Creates: the central warehouse and 3 branches; SA-0001 plus one dev user per role (WA, BA, FS) with
passwords from the environment (.env.example, local only); sample brands, items, prices and costs;
opening stock written through the stock service (ledger and audit rows), batched like a CSV import.
"""

import uuid
from decimal import Decimal
from typing import Any

from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from accounts.models import User, UserStatus
from accounts.services import create_user
from branches.models import Location, LocationKind
from inventory.models import (
    Brand,
    Category,
    Condition,
    ImportBatch,
    Item,
    ItemCost,
    ItemPrice,
    ItemStatus,
    Subtype,
)
from roles import constants as c
from stock_ledger.models import Bucket, MovementType, SourceType
from stock_ledger.services import StockChange, post_stock_changes

NAMESPACE = uuid.UUID("6f1c2f0e-3b53-4c1e-9f55-2f4f0f3d7a10")  # fixed, so batch operation IDs are stable

LOCATIONS = [
    ("WH", "Central Warehouse", LocationKind.WAREHOUSE),
    ("ACC", "Accra Central", LocationKind.BRANCH),
    ("KSI", "Kumasi", LocationKind.BRANCH),
    ("TKD", "Takoradi", LocationKind.BRANCH),
]
# (env key, full name, role, location code)
DEV_USERS = [
    ("SA", "Dev Super Admin", c.SUPER_ADMIN, None),
    ("WA", "Dev Warehouse Admin", c.WAREHOUSE_ADMIN, "WH"),
    ("BA", "Dev Branch Admin", c.BRANCH_ADMIN, "ACC"),
    ("FS", "Dev Front Staff", c.FRONT_STAFF, None),
]
BRANDS = ["HP", "Dell", "Lenovo", "Logitech"]
# sku, name, category, brand, condition, price, average cost
ITEMS = [
    ("SKU-000001", "HP 250 G9 Laptop", "Laptop", "HP", Condition.NEW, "3500.00", "2800.0000"),
    (
        "SKU-000002",
        "Dell Latitude 5420 Laptop",
        "Laptop",
        "Dell",
        Condition.REFURBISHED,
        "4200.00",
        "3300.0000",
    ),
    ("SKU-000003", "Lenovo ThinkPad T14 Laptop", "Laptop", "Lenovo", Condition.USED, "3900.00", "3000.0000"),
    ("SKU-000004", "HP 250 Laptop Battery", "Laptop Part", "HP", Condition.NEW, "250.00", "150.0000"),
    (
        "SKU-000005",
        "Logitech M185 Wireless Mouse",
        "Accessory",
        "Logitech",
        Condition.NEW,
        "90.00",
        "55.0000",
    ),
]
# location code -> {sku: opening quantity}
OPENING = {
    "WH": {"SKU-000001": 20, "SKU-000002": 10, "SKU-000003": 8, "SKU-000004": 40, "SKU-000005": 100},
    "ACC": {"SKU-000001": 5, "SKU-000005": 10},
    "KSI": {"SKU-000002": 3, "SKU-000005": 8},
    "TKD": {"SKU-000003": 2},
}


class Command(BaseCommand):
    help = "Seed local dev data (SA-0001, one dev user per role, branches, items, prices, stock). DEBUG only."

    def handle(self, *args: Any, **options: Any) -> None:
        if not settings.DEBUG:
            raise CommandError("seed_dev refuses to run when DEBUG is off (local use only).")
        passwords = self._passwords()
        with transaction.atomic():
            locations = self._locations()
            users = self._users(passwords, locations)
            items = self._catalogue()
            self._opening_stock(users["SA"], locations, items)
        for key, user in users.items():
            self.stdout.write(f"{user.login_id} ({key})")
        self.stdout.write("seed_dev: done")

    def _passwords(self) -> dict[str, str]:
        missing = [k for k, v in settings.DEV_SEED_PASSWORDS.items() if not v]
        if missing:
            raise CommandError(f"Set the dev seed passwords in .env (see .env.example): {', '.join(missing)}")
        for key, value in settings.DEV_SEED_PASSWORDS.items():
            try:
                validate_password(value)
            except ValidationError as exc:
                raise CommandError(f"Dev password for {key}: {exc.messages[0]}") from exc
        return dict(settings.DEV_SEED_PASSWORDS)

    def _locations(self) -> dict[str, Location]:
        return {
            code: Location.objects.get_or_create(code=code, defaults={"name": name, "kind": kind})[0]
            for code, name, kind in LOCATIONS
        }

    def _users(self, passwords: dict[str, str], locations: dict[str, Location]) -> dict[str, User]:
        users: dict[str, User] = {}
        for key, name, role, loc_code in DEV_USERS:
            user = User.objects.filter(full_name=name).first()
            if user is None:
                user, _otp = create_user(
                    full_name=name,
                    role_codes=[role],
                    permanent_location=locations[loc_code] if loc_code else None,
                )
                # Dev accounts are active so they can log in locally without the forced change.
                user.set_password(passwords[key])
                user.status = UserStatus.ACTIVE
                user.must_change_password = False
                user.one_time_password_issued_at = None
                user.save()
            users[key] = user
        return users

    def _catalogue(self) -> dict[str, Item]:
        brands = {n: Brand.objects.get_or_create(name=n)[0] for n in BRANDS}
        items: dict[str, Item] = {}
        for sku, name, category, brand, condition, price, cost in ITEMS:
            item, created = Item.objects.get_or_create(
                sku=sku,
                defaults={
                    "name": name,
                    "category": Category.objects.get(name=category),
                    "subtype": Subtype.objects.filter(category__name=category).order_by("id").first(),
                    "brand": brands[brand],
                    "model_name": name,
                    "mpn": sku,
                    "condition": condition,
                    "status": ItemStatus.ACTIVE,
                },
            )
            if created:
                ItemPrice.objects.create(item=item, selling_price=Decimal(price))
                ItemCost.objects.create(item=item, average_cost=Decimal(cost))
            items[sku] = item
        return items

    def _opening_stock(self, admin: User, locations: dict[str, Location], items: dict[str, Item]) -> None:
        for number, (loc_code, quantities) in enumerate(OPENING.items(), start=1):
            operation_id = uuid.uuid5(NAMESPACE, f"opening-{loc_code}")
            batch, created = ImportBatch.objects.get_or_create(
                operation_id=operation_id,
                defaults={
                    "reference": f"IMP-{number:06d}",
                    "location": locations[loc_code],
                    "file_name": "seed_dev",
                    "row_count": len(quantities),
                    "imported_by": admin,
                },
            )
            if not created:
                continue  # already seeded: nothing to post
            post_stock_changes(
                [
                    StockChange(
                        location=locations[loc_code],
                        item=items[sku],
                        bucket=Bucket.ON_HAND,
                        delta=qty,
                        movement_type=MovementType.OPENING_BALANCE,
                        source_type=SourceType.CSV_IMPORT,
                        source_id=batch.pk,
                        source_line_id=row,
                        source_ref=batch.reference,
                    )
                    for row, (sku, qty) in enumerate(quantities.items(), start=1)
                ],
                actor=admin,
                actor_role=c.SUPER_ADMIN,
                actor_location=locations[loc_code],
                operation_id=operation_id,
                note="Dev seed opening stock",
                audit_action="opening_stock_imported",
            )

"""Day 6 review (FIX-42..44): cost row lock order, sale cost read under the lock, CSV shape."""

import threading
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier
from typing import Any

import pytest
from django.db import connection, transaction

from inventory.models import Brand, Category, Item, ItemCost, ItemPrice, ItemStatus, StockBalance
from sales.models import SaleLine
from tests.api import call, client_as
from tests.test_b6_import import HEADER, nothing_written, send
from tests.test_b6_sales import sell, stock


@pytest.fixture
def two_items(locations: Any) -> tuple[Item, Item]:
    brand, cat = Brand.objects.create(name="HP"), Category.objects.get(name="Laptop")
    made = [
        Item.objects.create(sku=s, name=s, category=cat, brand=brand, status=ItemStatus.ACTIVE)
        for s in ("SKU-A", "SKU-B")
    ]
    return made[0], made[1]


# ---- FIX-42: import and receipt lock ItemCost rows in the same (item id) order ----


@pytest.mark.django_db(transaction=True)
def test_an_import_and_a_receipt_over_the_same_items_in_opposite_order_both_finish(
    users: dict[str, Any], locations: Any, two_items: tuple[Item, Item]
) -> None:
    a, b = two_items
    for item in (a, b):
        stock(locations["wh"], item, 10, "100.0000")
    wa_import, wa_receipt = client_as(users["wa"]), client_as(users["wa"])
    csv_text = f"sku,opening_quantity,unit_cost\n{b.sku},10,200.00\n{a.sku},10,200.00\n"  # B first, then A
    receipt = {
        "supplier_name": "Acme",
        "lines": [
            {"item_id": a.pk, "quantity": 10, "unit_cost": "300.00"},
            {"item_id": b.pk, "quantity": 10, "unit_cost": "300.00"},
        ],
    }
    barrier = Barrier(2)

    def do_import() -> int:
        try:
            barrier.wait()
            return int(send(wa_import, csv_text, dry_run=False).status_code)
        finally:
            connection.close()

    def do_receipt() -> int:
        try:
            barrier.wait()
            return int(call(wa_receipt, "POST", "/api/v1/goods-receipts/", receipt).status_code)
        finally:
            connection.close()

    with ThreadPoolExecutor(2) as pool:
        first, second = pool.submit(do_import), pool.submit(do_receipt)
        assert (first.result(timeout=60), second.result(timeout=60)) == (200, 201)
    for item in (a, b):
        assert StockBalance.objects.get(item=item).on_hand == 30
        # 100 then 200 then 300 over 10 each, or 100 then 300 then 200: both orders end near 200 to 216.67
        assert ItemCost.objects.get(item=item).average_cost in (Decimal("200.0000"), Decimal("216.6667"))


def test_a_dry_run_takes_no_cost_rows(
    users: dict[str, Any], locations: Any, two_items: tuple[Item, Item]
) -> None:
    a, _ = two_items
    stock(locations["wh"], a, 10, "100.0000")
    report = send(client_as(users["wa"]), f"sku,opening_quantity,unit_cost\n{a.sku},10,200.00\n").json()
    assert report["errors"] == [] and ItemCost.objects.get(item=a).average_cost == Decimal("100.0000")


# ---- FIX-43: the sale reads the cost under the lock ----


@pytest.mark.django_db(transaction=True)
def test_a_sale_waiting_for_a_cost_change_snapshots_the_new_cost(
    users: dict[str, Any], locations: Any, two_items: tuple[Item, Item]
) -> None:
    a, _ = two_items
    ItemPrice.objects.create(item=a, selling_price=Decimal("500.00"))
    stock(locations["a"], a, 5, "100.0000")
    ba = client_as(users["ba"])
    locked, release = threading.Event(), threading.Event()

    def receipt_like() -> None:
        try:
            with transaction.atomic():  # what a receipt does first: lock the cost row and change it
                ItemCost.objects.select_for_update().get(pk=a.pk)
                ItemCost.objects.filter(pk=a.pk).update(average_cost=Decimal("250.0000"))
                locked.set()
                release.wait(timeout=30)
        finally:
            connection.close()

    def do_sale() -> int:
        try:
            return int(sell(ba, [(a, 1)]).status_code)
        finally:
            connection.close()

    with ThreadPoolExecutor(2) as pool:
        holder = pool.submit(receipt_like)
        assert locked.wait(timeout=30)
        sale = pool.submit(do_sale)
        threading.Timer(1.5, release.set).start()  # the sale has had time to read a stale cost, if it did
        assert sale.result(timeout=60) == 201
        holder.result(timeout=60)
    assert SaleLine.objects.get().unit_cost_snapshot == Decimal("250.0000")


# ---- FIX-44: repeated header names and extra cells are errors ----


def test_a_repeated_column_name_is_refused(users: dict[str, Any], locations: Any) -> None:
    response = send(
        client_as(users["wa"]), "opening_quantity,unit_cost,unit_cost\n1,2.00,3.00\n", dry_run=False
    )
    assert response.status_code == 400 and "Repeated" in response.json()["message"]
    assert nothing_written()


def test_a_row_with_extra_cells_is_a_row_error(users: dict[str, Any], locations: Any) -> None:
    Brand.objects.create(name="HP")
    good = ",Cable2,Accessory,Mice,HP,C2,M2,new,1,2.00\n"
    text = f"{HEADER}\n,Cable,Accessory,Mice,HP,C1,M1,new,1,2.00,oops\n{good}"
    report = send(client_as(users["wa"]), text, dry_run=False).json()
    assert not report["committed"] and [(e["row"]) for e in report["errors"]] == [2]
    assert "extra" in report["errors"][0]["message"].lower()
    assert nothing_written()

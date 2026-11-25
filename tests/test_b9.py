"""B9.1-B9.4: Sprint 2 performance, security, backup and fixes."""

from time import monotonic

from rest_framework.test import APIClient

from inventory.models import Brand, Category, Item
from tests.api import call, client_as


def test_search_and_product_list_complete_within_two_seconds(
    users: dict[str, object], locations: dict[str, object]
) -> None:
    category = Category.objects.get(name="Laptop")
    brand = Brand.objects.create(name="Performance")
    items = [
        Item.objects.create(
            sku=f"PERF-{index:04d}",
            name=f"Performance Laptop {index}",
            model_name=f"P{index}",
            category=category,
            brand=brand,
            status="active",
        )
        for index in range(250)
    ]
    assert items

    client = client_as(users["sa"])
    started = monotonic()
    search = client.get("/api/v1/items/", {"q": "Performance"})
    search_elapsed = monotonic() - started
    assert search.status_code == 200
    assert search_elapsed < 2.0, search_elapsed
    assert search.json()["count"] >= 250

    started = monotonic()
    stock = client.get("/api/v1/stock/")
    stock_elapsed = monotonic() - started
    assert stock.status_code == 200
    assert stock_elapsed < 2.0, stock_elapsed


def test_mvp_state_change_and_data_endpoints_are_deny_by_default(
    users: dict[str, object], locations: dict[str, object]
) -> None:
    anonymous = APIClient()
    paths = [
        "/api/v1/goods-receipts/",
        "/api/v1/dispatches/",
        "/api/v1/sales/",
        "/api/v1/shortfalls/",
        "/api/v1/activity-log/",
        "/api/v1/items/",
        "/api/v1/stock/",
    ]
    for path in paths:
        response = anonymous.get(path)
        assert response.status_code in (401, 403), (path, response.status_code)

    for role in ("ba", "fs"):
        client = client_as(users[role])
        assert client.get("/api/v1/costed-stock/").status_code == 403
        assert client.get("/api/v1/costed-items/").status_code == 403
        assert client.get("/api/v1/costed-sales/").status_code == 403

    warehouse_admin = client_as(users["wa"])
    assert warehouse_admin.get("/api/v1/costed-stock/").status_code == 200
    assert warehouse_admin.get("/api/v1/costed-items/").status_code == 200
    assert warehouse_admin.get("/api/v1/costed-sales/").status_code == 403

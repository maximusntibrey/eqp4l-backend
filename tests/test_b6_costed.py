# ruff: noqa: F811  (pytest fixtures imported from test_b6_sales are redefined as arguments)
"""OQ-31 / contract 0.4.1: `/costed-sales/` is Super Admin only and shows the 4 dp snapshot at 2 dp; plain
`/sales/` never carries cost. Plus the Day 6 review findings."""

from decimal import Decimal
from typing import Any

import pytest
from rest_framework.test import APIClient

from inventory.models import ItemCost, ItemPrice
from sales.models import Sale
from tests.api import client_as
from tests.test_b6_sales import COST_WORDS, SALES, bal, items, keys, sell, shop, stock  # noqa: F401

COSTED = "/api/v1/costed-sales/"


@pytest.fixture
def sale(shop: dict[str, Any], items: dict[str, Any]) -> dict[str, Any]:
    ItemCost.objects.filter(item=items["x"]).update(average_cost=Decimal("2800.1250"))
    return dict(sell(shop["fs"], [(items["x"], 2)]).json())


def test_super_admin_sees_the_snapshot_at_two_dp_in_list_and_detail(
    shop: dict[str, Any],
    sale: dict[str, Any],
    items: dict[str, Any],
) -> None:
    ItemCost.objects.filter(item=items["x"]).update(average_cost=Decimal("1.0000"))  # a later change
    detail = shop["sa"].get(f"{COSTED}{sale['id']}/")
    assert detail.status_code == 200 and detail.json()["lines"][0]["unit_cost"] == "2800.13"
    assert (
        detail.json()["lines"][0]["unit_price"] == "250.50"
        and detail.json()["reference"] == sale["reference"]
    )
    page = shop["sa"].get(COSTED, {"status": "completed"}).json()
    assert [ln["unit_cost"] for r in page["results"] for ln in r["lines"]] == ["2800.13"]
    assert shop["sa"].get(COSTED, {"status": "cancelled"}).json()["results"] == []
    assert shop["sa"].get(f"{COSTED}99999/").status_code == 404
    assert shop["sa"].get(COSTED, {"status": "voided"}).status_code == 400


@pytest.mark.parametrize("role", ["ba", "fs", "wa"])
def test_other_roles_are_refused_the_costed_sales(
    role: str, shop: dict[str, Any], sale: dict[str, Any]
) -> None:
    for url in (COSTED, f"{COSTED}{sale['id']}/"):
        response = shop[role].get(url)
        assert response.status_code == 403 and response.json()["code"] == "permission_denied", (role, url)
        assert "2800" not in response.content.decode()
    assert APIClient().get(COSTED).status_code == 401


def test_plain_sales_never_carry_cost_for_any_role(
    shop: dict[str, Any],
    sale: dict[str, Any],
    items: dict[str, Any],
) -> None:
    for role in ("sa", "ba", "fs"):
        for url in (SALES, f"{SALES}{sale['id']}/"):
            body = shop[role].get(url)
            assert not (keys(body.json()) & set(COST_WORDS)) and "2800" not in body.content.decode(), (
                role,
                url,
            )
    for role in ("sa", "ba", "fs"):  # the write responses too
        created = sell(shop[role], [(items["y"], 1)])
        assert created.status_code == 201 and not (keys(created.json()) & set(COST_WORDS))


# ---------- Day 6 review findings ----------


def test_an_oversized_total_is_a_400_not_a_server_error(
    users: dict[str, Any],
    locations: Any,
    items: dict[str, Any],
) -> None:
    ItemPrice.objects.filter(item=items["x"]).update(selling_price=Decimal("9999999999.99"))
    stock(locations["a"], items["x"], 5)
    ba = client_as(users["ba"])
    response = sell(ba, [(items["x"], 5)])
    assert response.status_code == 400 and response.json()["errors"][0]["field"] == "lines"
    assert Sale.objects.count() == 0 and bal(locations["a"], items["x"]) == (5, 0)

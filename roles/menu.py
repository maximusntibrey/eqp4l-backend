"""Allowed menu per role (Frontend s3, at most 5 items; built by the server, enforced separately)."""

from roles import constants as c

_HOME = ("home", "Home", "/")
_FIND = ("find", "Find", "/find")
_SELL = ("sell", "Sell", "/sell")
_STOCK = ("stock", "Stock", "/stock")
_RECEIVE = ("receive", "Receive", "/receive")

MENUS: dict[str, list[tuple[str, str, str]]] = {
    c.FRONT_STAFF: [_SELL, _FIND, _STOCK, _RECEIVE],
    c.BRANCH_ADMIN: [_HOME, _SELL, _FIND, _STOCK, _RECEIVE],
    c.WAREHOUSE_ADMIN: [
        _HOME,
        ("items", "Items", "/items"),
        ("receive_stock", "Receive stock", "/receive-stock"),
        ("dispatch", "Dispatch", "/dispatch"),
        _FIND,
    ],
    c.SUPER_ADMIN: [
        _HOME,
        ("items", "Items", "/items"),
        ("warehouse", "Warehouse", "/warehouse"),
        ("branches", "Branches", "/branches"),
        ("users", "Users", "/users"),
    ],
}


def menu_for(role: str | None) -> list[dict[str, str]]:
    return [{"key": k, "label": label, "path": p} for k, label, p in MENUS.get(role or "", [])]

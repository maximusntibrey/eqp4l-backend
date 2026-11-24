"""Allowed menu per role (Frontend s3, at most 5 nav items; built by the server, enforced separately).

OQ-23 (contract v0.1.2): Super Admin opens Sell, Activity, Find and Receive from Home, so they are
`home_links` (separate from `menu`), so they never take one of the 5 nav slots. The actions behind them are
`sales.record` (also Sales, row 49), `activity.view`, `find.use` and `dispatches.receive` (roles.permissions).
"""

from roles import constants as c

_HOME = ("home", "Home", "/")
_FIND = ("find", "Find", "/find")
_SELL = ("sell", "Sell", "/sell")
_STOCK = ("stock", "Stock", "/stock")
_RECEIVE = ("receive", "Receive", "/receive")
_ACTIVITY = ("activity", "Activity", "/activity")
_SALES = ("sales", "Sales", "/sales")  # row 49 (v0.4.2)

MENUS: dict[str, list[tuple[str, str, str]]] = {
    c.FRONT_STAFF: [_SELL, _FIND, _STOCK, _RECEIVE, _SALES],
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
HOME_LINKS: dict[str, list[tuple[str, str, str]]] = {
    c.SUPER_ADMIN: [_ACTIVITY, _SELL, _FIND, _RECEIVE, _SALES],  # menu is full: Sales is a Home tile
    c.WAREHOUSE_ADMIN: [_ACTIVITY],  # OQ-25: own location's activity only (OQ-5)
    c.BRANCH_ADMIN: [_ACTIVITY, _SALES],  # menu is full (5): Sales is a Home tile
}


def menu_for(role: str | None) -> list[dict[str, str]]:
    return [{"key": k, "label": label, "path": p} for k, label, p in MENUS.get(role or "", [])]


def home_links_for(role: str | None) -> list[dict[str, str]]:
    """Home tiles, separate from the max-5 `menu` (OQ-23)."""
    return [{"key": k, "label": label, "path": p} for k, label, p in HOME_LINKS.get(role or "", [])]

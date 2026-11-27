"""Role and per-person permission codes (ERD roles, user_permissions; contract RoleCode)."""

SUPER_ADMIN = "super_admin"
WAREHOUSE_ADMIN = "warehouse_admin"
BRANCH_ADMIN = "branch_admin"
FRONT_STAFF = "front_staff"
CENTRAL_WAREHOUSE = "central_warehouse"  # read-only view across all warehouses (contract 0.8.0)

# Order matters: the first role a user holds is their active role until role switching (Sprint 5).
ROLE_PRIORITY = [SUPER_ADMIN, WAREHOUSE_ADMIN, CENTRAL_WAREHOUSE, BRANCH_ADMIN, FRONT_STAFF]
ROLE_NAMES = {
    SUPER_ADMIN: "Super Admin",
    WAREHOUSE_ADMIN: "Warehouse Admin",
    BRANCH_ADMIN: "Branch Admin",
    FRONT_STAFF: "Front Staff",
    CENTRAL_WAREHOUSE: "Central Warehouse",
}

RECEIVE_STOCK = "receive_stock"
MANAGE_PRICES = "manage_prices"
DISCOUNT = "discount"
PERSON_PERMISSIONS = [RECEIVE_STOCK, MANAGE_PRICES, DISCOUNT]

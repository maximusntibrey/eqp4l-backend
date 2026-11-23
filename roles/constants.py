"""Role and per-person permission codes (ERD roles, user_permissions; contract RoleCode)."""

SUPER_ADMIN = "super_admin"
WAREHOUSE_ADMIN = "warehouse_admin"
BRANCH_ADMIN = "branch_admin"
FRONT_STAFF = "front_staff"

# Order matters: the first role a user holds is their active role until role switching (Sprint 5).
ROLE_PRIORITY = [SUPER_ADMIN, WAREHOUSE_ADMIN, BRANCH_ADMIN, FRONT_STAFF]
ROLE_NAMES = {
    SUPER_ADMIN: "Super Admin",
    WAREHOUSE_ADMIN: "Warehouse Admin",
    BRANCH_ADMIN: "Branch Admin",
    FRONT_STAFF: "Front Staff",
}

RECEIVE_STOCK = "receive_stock"
MANAGE_PRICES = "manage_prices"
DISCOUNT = "discount"
PERSON_PERMISSIONS = [RECEIVE_STOCK, MANAGE_PRICES, DISCOUNT]

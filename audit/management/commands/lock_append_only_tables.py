"""Layer 3 of the append-only rule (ERD s4): the application's database role gets INSERT and SELECT only.

Run once per environment where the host allows a separate migration role (DevOps s4), as the table owner:
    python manage.py lock_append_only_tables --role app_runtime
"""

import re
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import connection

APPEND_ONLY_TABLES = [
    "stock_ledger_stockmovement",
    "audit_auditevent",
    "accounts_loginlog",
    "branch_access_switchlog",
    "transfers_dispatchresolution",
    "inventory_importbatch",
]


class Command(BaseCommand):
    help = "Revoke UPDATE, DELETE and TRUNCATE on the append-only tables from the application role."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--role", required=True, help="PostgreSQL role the application connects as")

    def handle(self, *args: Any, **options: Any) -> None:
        role = options["role"]
        if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", role):
            raise CommandError("Role name must be lowercase letters, digits and underscores.")
        quoted = connection.ops.quote_name(role)
        with connection.cursor() as cursor:
            for table in APPEND_ONLY_TABLES:
                cursor.execute(f"REVOKE ALL ON {table} FROM {quoted}")
                cursor.execute(f"GRANT SELECT, INSERT ON {table} TO {quoted}")
        self.stdout.write(f"{role}: SELECT and INSERT only on {len(APPEND_ONLY_TABLES)} append-only tables.")

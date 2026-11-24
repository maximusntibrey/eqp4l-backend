import os
from collections.abc import Callable, Iterator
from typing import Any

# Settings read env at import; make sure tests never depend on a developer's .env.
os.environ.setdefault("DJANGO_DEBUG", "True")
os.environ.setdefault("DJANGO_SECRET_KEY", "test-only-secret-key")

import pytest
from rest_framework.test import APIClient

PASSWORD = "correct-horse-battery"
APPEND_ONLY_TABLES = [
    "stock_ledger_stockmovement",
    "audit_auditevent",
    "accounts_loginlog",
    "branch_access_switchlog",
    "transfers_dispatchresolution",
    "inventory_importbatch",
    "accounts_loginidsequence",  # not append-only, but TRUNCATE-guarded too
]


@pytest.fixture(scope="session", autouse=True)
def _flush_may_truncate_append_only_tables() -> Iterator[None]:
    """Transactional tests end with Django's TRUNCATE flush, which the append-only triggers (rightly) refuse.

    Test-only: wrap the flush statements so the triggers are off for that one transaction and back on after.
    Production code has no such switch.
    """
    from django.db.backends.postgresql.operations import DatabaseOperations

    original = DatabaseOperations.sql_flush

    def sql_flush(self: Any, style: Any, tables: Any, **kwargs: Any) -> list[str]:
        statements = original(self, style, tables, **kwargs)
        off = [f"ALTER TABLE {t} DISABLE TRIGGER USER;" for t in APPEND_ONLY_TABLES]
        on = [f"ALTER TABLE {t} ENABLE TRIGGER USER;" for t in APPEND_ONLY_TABLES]
        return off + list(statements) + on

    DatabaseOperations.sql_flush = sql_flush  # type: ignore[method-assign]
    yield
    DatabaseOperations.sql_flush = original  # type: ignore[method-assign]


@pytest.fixture(autouse=True)
def _fast_password_hasher(settings: Any) -> None:
    settings.PASSWORD_HASHERS = ["tests.fast_hasher.FastArgon2PasswordHasher"]


@pytest.fixture
def locations(db: None) -> dict[str, Any]:
    from branches.models import Location, LocationKind

    return {
        "wh": Location.objects.create(kind=LocationKind.WAREHOUSE, code="WH", name="Central Warehouse"),
        "a": Location.objects.create(kind=LocationKind.BRANCH, code="A", name="Branch A"),
        "b": Location.objects.create(kind=LocationKind.BRANCH, code="B", name="Branch B"),
    }


@pytest.fixture
def make_user(db: None, locations: dict[str, Any]) -> Callable[..., Any]:
    """make_user("branch_admin", "a") -> active user with PASSWORD and no forced change."""
    from accounts.models import UserStatus
    from accounts.services import create_user

    def _make(
        role: str, location: str | None = None, *, status: str = UserStatus.ACTIVE, **extra: Any
    ) -> Any:
        user, otp = create_user(
            full_name=f"Test {role}",
            role_codes=[role],
            permanent_location=locations[location] if location else None,
        )
        user.set_password(PASSWORD)
        user.status = status
        user.must_change_password = extra.pop("must_change_password", False)
        user.one_time_password_issued_at = extra.pop("issued", None)
        user.save()
        user.otp = otp  # type: ignore[attr-defined]
        return user

    return _make


@pytest.fixture
def users(make_user: Callable[..., Any]) -> dict[str, Any]:
    """One active user per role."""
    return {
        "sa": make_user("super_admin"),
        "wa": make_user("warehouse_admin", "wh"),
        "ba": make_user("branch_admin", "a"),
        "fs": make_user("front_staff"),
    }


def login(client: APIClient, user: Any, password: str = PASSWORD) -> Any:
    """Log in through the real endpoint (CSRF header included)."""
    token = client.get("/api/v1/auth/csrf/").json()["csrf_token"]
    response = client.post(
        "/api/v1/auth/login/",
        {"login_id": user.login_id, "password": password},
        format="json",
        HTTP_X_CSRFTOKEN=token,
    )
    if response.status_code == 200:
        client.credentials(HTTP_X_CSRFTOKEN=client.cookies["csrftoken"].value)
    return response


@pytest.fixture
def api() -> APIClient:
    return APIClient()

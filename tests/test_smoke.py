"""Tooling smoke tests (step B1.0): settings load, Argon2 hashing works, the OpenAPI
contract generator runs, and the test database is real PostgreSQL."""

import pytest
from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.db import connection
from drf_spectacular.generators import SchemaGenerator


def test_settings_load_with_safe_defaults() -> None:
    assert settings.USE_TZ is True
    assert settings.TIME_ZONE == "Africa/Accra"
    assert settings.DATABASES["default"]["ENGINE"] == "django.db.backends.postgresql"
    assert settings.SESSION_COOKIE_HTTPONLY is True
    assert settings.REST_FRAMEWORK["DEFAULT_PERMISSION_CLASSES"] == [
        "rest_framework.permissions.IsAuthenticated",
    ]


def test_passwords_are_hashed_with_argon2() -> None:
    assert settings.PASSWORD_HASHERS[0] == "django.contrib.auth.hashers.Argon2PasswordHasher"
    hashed = make_password("not-a-real-password")
    assert hashed.startswith("argon2$")
    assert check_password("not-a-real-password", hashed)
    assert not check_password("wrong-password", hashed)


def test_openapi_schema_generates() -> None:
    schema = SchemaGenerator().get_schema(request=None, public=True)
    assert str(schema["openapi"]).startswith("3.")
    assert schema["info"]["title"] == "Payless4Laptops Inventory & Warehouse API"


@pytest.mark.django_db
def test_database_is_postgresql() -> None:
    assert connection.vendor == "postgresql"
    with connection.cursor() as cursor:
        cursor.execute("SELECT version()")
        row = cursor.fetchone()
    assert row is not None
    assert str(row[0]).startswith("PostgreSQL")

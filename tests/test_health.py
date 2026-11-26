from unittest import mock

import pytest
from django.db import OperationalError
from rest_framework.test import APIClient


@pytest.mark.django_db
def test_health_ok() -> None:
    response = APIClient().get("/health/")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


def test_health_503_when_database_down() -> None:
    with mock.patch("config.health.connection") as conn:
        conn.cursor.side_effect = OperationalError("connection refused")
        response = APIClient().get("/health/")
    assert response.status_code == 503
    assert response.json() == {"status": "error", "database": "unavailable"}


@pytest.mark.django_db
def test_health_needs_no_login_and_rejects_post() -> None:
    assert APIClient().post("/health/").status_code == 405

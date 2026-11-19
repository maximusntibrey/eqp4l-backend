"""O1.7: /health/ and Sentry wiring."""

from unittest.mock import MagicMock, patch

import pytest
from django.db import OperationalError
from django.test import Client

from eqp4l import monitoring


@pytest.mark.django_db
def test_health_ok_when_database_reachable(client: Client) -> None:
    response = client.get("/health/")
    assert response.status_code == 200
    assert response.content == b"ok"
    assert response["Content-Type"].startswith("text/plain")
    assert "no-cache" in response["Cache-Control"]


def test_health_503_when_database_down(client: Client, caplog: pytest.LogCaptureFixture) -> None:
    with (
        caplog.at_level("ERROR"),
        patch(
            "eqp4l.health.connection.cursor",
            side_effect=OperationalError(
                "could not connect to server at host db-secret-host password=hunter2"
            ),
        ),
    ):
        response = client.get("/health/")
    assert response.status_code == 503
    assert response.content == b"unavailable"
    assert b"secret" not in response.content
    # SKILLS rule 17: the log names the failure class only, never the host or a secret.
    assert "OperationalError" in caplog.text
    assert "db-secret-host" not in caplog.text
    assert "hunter2" not in caplog.text


@pytest.mark.django_db
def test_health_needs_no_login_and_head_works(client: Client) -> None:
    assert client.head("/health/").status_code == 200


@pytest.mark.django_db
@pytest.mark.parametrize("method", ["post", "put", "patch", "delete"])
def test_health_rejects_unsafe_methods(client: Client, method: str) -> None:
    assert getattr(client, method)("/health/").status_code == 405


@pytest.mark.django_db
def test_health_real_post_is_stopped_by_csrf() -> None:
    # CSRF middleware runs before require_safe, so a real POST gets 403, not 405.
    strict = Client(enforce_csrf_checks=True)
    assert strict.post("/health/").status_code == 403


def test_sentry_stays_off_without_dsn() -> None:
    with patch("sentry_sdk.init") as init:
        assert monitoring.init_sentry("", "staging", "v1") is False
    init.assert_not_called()


def test_sentry_uses_env_values_and_no_pii() -> None:
    with patch("sentry_sdk.init", MagicMock()) as init:
        assert monitoring.init_sentry("https://k@example.invalid/1", "staging", "v1.2") is True
    init.assert_called_once_with(
        dsn="https://k@example.invalid/1",
        environment="staging",
        release="v1.2",
        send_default_pii=False,
    )


def test_sentry_not_initialised_in_test_settings() -> None:
    import sentry_sdk

    assert sentry_sdk.get_client().is_active() is False

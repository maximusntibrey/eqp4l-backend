import importlib
from collections.abc import Iterator
from unittest import mock

import pytest
from django.core.management import call_command

import config.settings as settings_module


@pytest.fixture
def reload_settings(monkeypatch: pytest.MonkeyPatch) -> Iterator[object]:
    def _reload(**env: str) -> object:
        monkeypatch.setattr("environ.Env.read_env", lambda *a, **k: None)  # ignore a local .env
        for key, value in env.items():
            monkeypatch.setenv(key, value)
        return importlib.reload(settings_module)

    yield _reload
    monkeypatch.undo()
    importlib.reload(settings_module)


def test_secure_cookies_default_on_when_not_debug(reload_settings) -> None:  # type: ignore[no-untyped-def]
    s = reload_settings(DJANGO_DEBUG="False")
    assert s.SESSION_COOKIE_SECURE and s.CSRF_COOKIE_SECURE and s.SECURE_SSL_REDIRECT
    assert s.SESSION_COOKIE_HTTPONLY


def test_secure_cookies_are_env_driven(reload_settings) -> None:  # type: ignore[no-untyped-def]
    s = reload_settings(DJANGO_DEBUG="False", SESSION_COOKIE_SECURE="False", SESSION_COOKIE_SAMESITE="Strict")
    assert s.SESSION_COOKIE_SECURE is False
    assert s.SESSION_COOKIE_SAMESITE == "Strict"


def test_secret_key_required_outside_debug(reload_settings, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delenv("DJANGO_SECRET_KEY")
    with pytest.raises(RuntimeError, match="DJANGO_SECRET_KEY"):
        reload_settings(DJANGO_DEBUG="False")


def test_sentry_not_initialised_without_dsn(reload_settings, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    with mock.patch("sentry_sdk.init") as init:
        reload_settings()
    init.assert_not_called()


def test_sentry_initialised_with_dsn(reload_settings) -> None:  # type: ignore[no-untyped-def]
    with mock.patch("sentry_sdk.init") as init:
        reload_settings(SENTRY_DSN="https://key@example.invalid/1")
    init.assert_called_once()
    assert init.call_args.kwargs["dsn"] == "https://key@example.invalid/1"


def test_openapi_schema_generates_with_health(tmp_path) -> None:  # type: ignore[no-untyped-def]
    out = tmp_path / "schema.yaml"
    call_command("spectacular", file=str(out), validate=True)
    assert "/health/" in out.read_text()


def test_debug_defaults_to_false_when_env_unset(reload_settings, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delenv("DJANGO_DEBUG", raising=False)
    assert reload_settings(DJANGO_SECRET_KEY="x" * 50).DEBUG is False


@pytest.mark.django_db
def test_health_over_http_is_not_redirected_when_debug_off(reload_settings, settings) -> None:  # type: ignore[no-untyped-def]
    # Container health checks call plain http; the SSL redirect must not turn /health/ into a 301.
    s = reload_settings(DJANGO_DEBUG="False", DJANGO_SECRET_KEY="x" * 50)
    assert s.SECURE_SSL_REDIRECT
    settings.SECURE_SSL_REDIRECT = s.SECURE_SSL_REDIRECT
    settings.SECURE_REDIRECT_EXEMPT = s.SECURE_REDIRECT_EXEMPT
    settings.ALLOWED_HOSTS = ["testserver"]
    from rest_framework.test import APIClient

    client = APIClient()
    assert client.get("/health/").status_code == 200
    assert client.get("/api/v1/auth/me/").status_code == 301  # everything else still redirects

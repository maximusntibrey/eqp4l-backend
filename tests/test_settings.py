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


def test_railway_environment_aliases(reload_settings) -> None:  # type: ignore[no-untyped-def]
    s = reload_settings(
        DEBUG="False",
        SECRET_KEY="x" * 50,
        ALLOWED_HOSTS="backend.up.railway.app",
        CSRF_TRUSTED_ORIGINS="https://frontend.up.railway.app",
        CORS_ALLOWED_ORIGINS="https://frontend.up.railway.app",
        SECURE_PROXY_SSL_HEADER_ENABLED="True",
    )
    assert s.ALLOWED_HOSTS == ["backend.up.railway.app"]
    assert s.CSRF_TRUSTED_ORIGINS == ["https://frontend.up.railway.app"]
    assert s.CORS_ALLOWED_ORIGINS == ["https://frontend.up.railway.app"]
    assert s.CORS_ALLOW_ALL_ORIGINS is False
    assert s.SECURE_PROXY_SSL_HEADER == ("HTTP_X_FORWARDED_PROTO", "https")


@pytest.mark.django_db
def test_cors_exposes_retry_after_to_frontend(settings) -> None:  # type: ignore[no-untyped-def]
    from rest_framework.test import APIClient

    origin = "http://localhost:5173"
    settings.CORS_ALLOWED_ORIGINS = [origin]
    response = APIClient().get("/health/", HTTP_ORIGIN=origin)

    assert response["Access-Control-Allow-Origin"] == origin
    assert "retry-after" in response["Access-Control-Expose-Headers"].lower()


@pytest.mark.django_db
def test_cors_preflight_allows_idempotency_key_header(settings) -> None:  # type: ignore[no-untyped-def]
    """Every write sends Idempotency-Key; the browser preflight must allow it or writes fail cross-site."""
    from rest_framework.test import APIClient

    origin = "https://frontend.up.railway.app"
    settings.CORS_ALLOWED_ORIGINS = [origin]
    response = APIClient().options(
        "/api/v1/items/",
        HTTP_ORIGIN=origin,
        HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST",
        HTTP_ACCESS_CONTROL_REQUEST_HEADERS="content-type,x-csrftoken,idempotency-key",
    )

    assert response.status_code == 200
    allowed = response["Access-Control-Allow-Headers"].lower()
    assert "idempotency-key" in allowed and "x-csrftoken" in allowed


def test_local_sqlite_and_volume_media_fallbacks(reload_settings, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delenv("DATABASE_URL", raising=False)
    s = reload_settings(DJANGO_DEBUG="True", DJANGO_SECRET_KEY="x" * 50)
    assert s.DATABASES["default"]["ENGINE"] == "django.db.backends.sqlite3"

    s = reload_settings(DJANGO_DEBUG="False", SECRET_KEY="x" * 50, MEDIA_ROOT="/data/media")
    assert str(s.MEDIA_ROOT) == "/data/media"


def test_static_and_media_storage_backends(reload_settings) -> None:  # type: ignore[no-untyped-def]
    s = reload_settings(DEBUG="False", SECRET_KEY="x" * 50)
    assert s.STORAGES["staticfiles"]["BACKEND"].endswith("ManifestStaticFilesStorage")
    assert s.STORAGES["default"]["BACKEND"].endswith("FileSystemStorage")


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


def test_sentry_sends_no_local_variables_or_pii(reload_settings) -> None:  # type: ignore[no-untyped-def]
    # sentry-sdk 3.x has no include_local_variables/send_default_pii; data_collection is the equivalent.
    with mock.patch("sentry_sdk.init") as init:
        reload_settings(SENTRY_DSN="https://key@example.invalid/1")
    dc = init.call_args.kwargs["data_collection"]
    assert dc["user_info"] is False and dc["stack_frame_variables"] is False and dc["http_bodies"] == []


def test_sentry_options_are_accepted_by_the_installed_sdk(reload_settings) -> None:  # type: ignore[no-untyped-def]
    import sentry_sdk

    reload_settings(SENTRY_DSN="https://key@example.invalid/1")  # real init: an unknown option raises
    assert sentry_sdk.get_client().options["data_collection"]["stack_frame_variables"] is False
    sentry_sdk.init()  # leave Sentry off for later tests

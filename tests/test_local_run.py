"""FIX-1: local-run safety. Insecure cookies only in local mode, LF line endings."""

import os
import shutil
import subprocess  # nosec B404 - tests run the project's own interpreter and git
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

_BASE_ENV = {  # nosec B105 - dummy test values
    "DJANGO_SECRET_KEY": "test-only-not-a-secret",
    "DATABASE_URL": "postgres://u:p@127.0.0.1:5432/db",
    "DJANGO_DEBUG": "false",
    "DJANGO_LOCAL": "false",
    "DJANGO_ALLOWED_HOSTS": "example.test",
    "CSRF_TRUSTED_ORIGINS": "https://app.example.test",
    "SESSION_COOKIE_SECURE": "true",
    "CSRF_COOKIE_SECURE": "true",
}


def _run(code: str, **overrides: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, **_BASE_ENV, **overrides}
    return subprocess.run(  # noqa: S603  # nosec B603
        [sys.executable, "-c", code],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_insecure_cookies_refused_outside_local_mode() -> None:
    result = _run("import eqp4l.settings", SESSION_COOKIE_SECURE="false")
    assert result.returncode != 0
    assert "ImproperlyConfigured" in result.stderr
    result = _run("import eqp4l.settings", CSRF_COOKIE_SECURE="false")
    assert result.returncode != 0


def test_insecure_cookies_allowed_in_local_mode() -> None:
    for local in ({"DJANGO_LOCAL": "true"}, {"DJANGO_DEBUG": "true"}):
        result = _run(
            "import eqp4l.settings as s; assert s.SESSION_COOKIE_SECURE is False",
            SESSION_COOKIE_SECURE="false",
            CSRF_COOKIE_SECURE="false",
            **local,
        )
        assert result.returncode == 0, result.stderr


def test_vite_origins_trusted_only_in_local_mode() -> None:
    code = "import eqp4l.settings as s; print(','.join(s.CSRF_TRUSTED_ORIGINS))"
    prod = _run(code)
    assert prod.returncode == 0, prod.stderr
    assert "localhost:5173" not in prod.stdout
    local = _run(code, DJANGO_LOCAL="true")
    assert "http://localhost:5173" in local.stdout
    assert "http://127.0.0.1:5173" in local.stdout


def test_deploy_check_has_no_cookie_warnings_in_production_mode() -> None:
    """`check --deploy` in a production-like environment raises no cookie warnings."""
    code = (
        "import django, os; os.environ['DJANGO_SETTINGS_MODULE']='eqp4l.settings'; django.setup();"
        "from django.core.checks import run_checks;"
        "ids={m.id for m in run_checks(include_deployment_checks=True)};"
        "bad={'security.W010','security.W011','security.W012','security.W016'};"
        "assert not ids & bad, ids"
    )
    result = _run(code)
    assert result.returncode == 0, result.stdout + result.stderr


def test_gitattributes_forces_lf_for_scripts_and_docker_files() -> None:
    lines = (ROOT / ".gitattributes").read_text(encoding="utf-8").splitlines()
    for pattern in ("*.sh", "*.py", "Dockerfile", "docker/entrypoint.sh"):
        assert f"{pattern} text eol=lf" in lines, f"{pattern} must be LF in .gitattributes"


@pytest.mark.parametrize(
    "path",
    ["docker/entrypoint.sh", "Dockerfile", "compose.yaml", "scripts/dev.sh", "scripts/check.sh"],
)
def test_files_in_working_tree_have_no_crlf(path: str) -> None:
    assert b"\r" not in (ROOT / path).read_bytes(), f"{path} contains CR characters"


def test_entrypoint_is_executable_in_git() -> None:
    git = shutil.which("git")
    if git is None or not (ROOT / ".git").exists():
        pytest.skip("git checkout not available")
    out = subprocess.run(  # noqa: S603
        [git, "ls-files", "-s", "docker/entrypoint.sh", "scripts/dev.sh"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    ).stdout.splitlines()
    assert len(out) == 2, out
    assert all(line.startswith("100755") for line in out), out


def test_entrypoint_seed_is_guarded_not_faked() -> None:
    text = (ROOT / "docker/entrypoint.sh").read_text(encoding="utf-8")
    assert 'DJANGO_SEED_DEV:-0}" = "1"' in text
    assert "help seed_dev" in text

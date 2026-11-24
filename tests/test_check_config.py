"""Guards for the check command itself (FIX-13..FIX-16): scans and gates must cover all app code."""

import tomllib
from pathlib import Path

import yaml
from django.conf import settings

ROOT = Path(__file__).resolve().parent.parent


def test_bandit_scans_whole_project() -> None:
    check = (ROOT / "scripts" / "check.sh").read_text(encoding="utf-8")
    assert "bandit -q -r . " in check


def test_coverage_measures_whole_project() -> None:
    cfg = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert "--cov=. " in cfg["tool"]["pytest"]["ini_options"]["addopts"]


def test_production_start_does_not_auto_migrate_by_default() -> None:
    start = (ROOT / "scripts" / "start.sh").read_text(encoding="utf-8")
    assert 'if [ "${AUTO_MIGRATE:-False}" = "True" ]; then\n  python manage.py migrate' in start


def test_generated_schema_version_matches_published_contract() -> None:
    contract = yaml.safe_load((ROOT / "docs" / "api" / "openapi.yaml").read_text(encoding="utf-8"))
    assert settings.SPECTACULAR_SETTINGS["VERSION"] == contract["info"]["version"]

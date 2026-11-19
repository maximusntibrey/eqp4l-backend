"""The app image must contain every project app (a missing COPY broke the image in B2.1)."""

import re
from pathlib import Path

from django.conf import settings

ROOT = Path(settings.BASE_DIR)


def _apps() -> set[str]:
    return {p.parent.name for p in ROOT.glob("*/apps.py")}


def test_dockerfile_copies_every_project_app() -> None:
    copied = set(re.findall(r"^COPY (\w+) \./\1$", (ROOT / "Dockerfile").read_text(), re.M))
    assert _apps(), "no project apps found"
    assert _apps() <= copied, f"Dockerfile does not COPY: {sorted(_apps() - copied)}"
    assert "eqp4l" in copied


def test_every_project_app_is_installed() -> None:
    assert _apps() <= set(settings.INSTALLED_APPS)

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings
from pytest import CaptureFixture

from accounts.models import User
from roles import constants as c
from roles.services import role_codes


@pytest.mark.django_db
@override_settings(DEBUG=False)
def test_create_production_superadmin_creates_one_pending_account(capsys: CaptureFixture[str]) -> None:
    call_command("create_production_superadmin", full_name="Production Owner")
    output = capsys.readouterr().out
    user = User.objects.get(login_id="SA-0001")
    assert c.SUPER_ADMIN in role_codes(user)
    assert user.status == "pending_activation"
    assert user.must_change_password is True
    assert "Login ID: SA-0001" in output
    assert "One-time password:" in output
    with pytest.raises(CommandError, match="A Super Admin already exists"):
        call_command("create_production_superadmin", full_name="Second Owner")


@override_settings(DEBUG=True)
def test_create_production_superadmin_refuses_debug_mode() -> None:
    with pytest.raises(CommandError, match="DEBUG is true"):
        call_command("create_production_superadmin", full_name="Production Owner")

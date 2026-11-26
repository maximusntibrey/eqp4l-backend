"""Create the first production Super Admin account once."""

from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from accounts.models import User
from accounts.services import create_user
from audit.services import record_event
from roles import constants as c
from roles.services import role_codes


class Command(BaseCommand):
    help = "Create the first production Super Admin. DEBUG must be false."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--full-name", required=True)

    def handle(self, *args: Any, **options: Any) -> str | None:
        if settings.DEBUG:
            raise CommandError("Refusing to create a production Super Admin while DEBUG is true.")
        if any(c.SUPER_ADMIN in role_codes(user) for user in User.objects.all()):
            raise CommandError("A Super Admin already exists.")

        with transaction.atomic():
            user, one_time_password = create_user(
                full_name=options["full_name"],
                role_codes=[c.SUPER_ADMIN],
            )
            record_event(
                "user_created",
                actor=None,
                actor_login_id="bootstrap",
                actor_role="super_admin",
                target_type="user",
                target_ref=user.login_id,
            )

        self.stdout.write(f"Login ID: {user.login_id}")
        self.stdout.write(f"One-time password: {one_time_password}")
        self.stdout.write("This password is shown once. The account must change it at first login.")
        return None

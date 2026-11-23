from django.apps import AppConfig
from django.contrib.auth.signals import user_logged_in
from django.db.models.signals import post_migrate


class AccountsConfig(AppConfig):
    name = "accounts"

    def ready(self) -> None:
        from django.contrib.auth.models import update_last_login

        from accounts import schema  # noqa: F401  (registers the OpenAPI auth scheme)

        # The user table has last_login_at (ERD), not Django's last_login; the login service sets it.
        from config.reference_data import ensure_reference_data

        post_migrate.connect(ensure_reference_data, sender=self, dispatch_uid="ensure_reference_data")
        user_logged_in.disconnect(update_last_login, dispatch_uid="update_last_login")

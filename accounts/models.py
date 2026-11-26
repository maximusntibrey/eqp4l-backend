from django.conf import settings
from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.db import models

from config.append_only import AppendOnlyModel
from config.dbutils import choice_check


class UserStatus(models.TextChoices):
    ACTIVE = "active"
    PENDING_ACTIVATION = "pending_activation"
    SUSPENDED = "suspended"
    DEACTIVATED = "deactivated"


class UserManager(BaseUserManager["User"]):
    """Users are created only by `accounts.services.create_user`, so IDs come from one generator."""

    def get_by_natural_key(self, username: str | None) -> "User":
        return self.get(login_id=username)


class User(AbstractBaseUser):
    login_id = models.CharField(max_length=20, unique=True)  # SA-0001 / USR-0001, immutable (DB trigger)
    full_name = models.CharField(max_length=150)
    status = models.CharField(
        max_length=20, choices=UserStatus.choices, default=UserStatus.PENDING_ACTIVATION
    )
    must_change_password = models.BooleanField(default=True)
    one_time_password_issued_at = models.DateTimeField(null=True, blank=True)
    permanent_location = models.ForeignKey(
        "branches.Location", null=True, blank=True, on_delete=models.PROTECT, related_name="permanent_users"
    )
    last_login_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT, related_name="+")

    # The ERD names the column last_login_at; Django's own last_login is dropped (its signal is disconnected).
    last_login = None

    USERNAME_FIELD = "login_id"
    objects = UserManager()

    class Meta:
        constraints = [
            choice_check("status", UserStatus, "users_status_valid"),
            models.CheckConstraint(
                condition=models.Q(login_id__regex=r"^(SA|USR)-[0-9]{4,}$"), name="users_login_id_format"
            ),
        ]

    @property
    def is_active(self) -> bool:  # type: ignore[override]
        """Only active and pending-activation accounts may hold a session."""
        return self.status in (UserStatus.ACTIVE, UserStatus.PENDING_ACTIVATION)

    def __str__(self) -> str:
        return self.login_id


class LoginIdSequence(models.Model):
    """One row per prefix (SA, USR). last_number only ever increases, so IDs are never reused."""

    prefix = models.CharField(max_length=3, primary_key=True)
    last_number = models.IntegerField(default=0)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=models.Q(last_number__gte=0), name="login_seq_non_negative")
        ]


class LoginEvent(models.TextChoices):
    SUCCESS = "login_success"
    FAILED = "login_failed"
    LOGOUT = "logout"


class LoginLog(AppendOnlyModel):
    """Every login success, failure and logout. Also drives the rate limit. Never holds passwords."""

    login_id_attempted = models.CharField(max_length=64)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT, related_name="+")
    event = models.CharField(max_length=20, choices=LoginEvent.choices)
    failure_reason = models.CharField(max_length=40, blank=True)
    ip = models.GenericIPAddressField(null=True)
    user_agent = models.TextField(blank=True)
    at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [choice_check("event", LoginEvent, "login_log_event_valid")]
        indexes = [models.Index(fields=["login_id_attempted", "ip", "at"], name="login_log_rate_idx")]

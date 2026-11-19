"""The custom user model (ERD s3.1). ``AUTH_USER_MODEL = "accounts.User"``."""

from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.db import models
from django.db.models import Q

from eqp4l.db import AuditFields


class UserStatus(models.TextChoices):
    PENDING = "pending"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    DEACTIVATED = "deactivated"


class UserManager(BaseUserManager["User"]):
    """Users are created through ``create_user`` from B2.2 (login ID generator)."""


class User(AuditFields, AbstractBaseUser):
    login_id = models.CharField(max_length=12, unique=True, editable=False)
    full_name = models.CharField(max_length=150)
    phone = models.CharField(max_length=30)
    email = models.EmailField(max_length=254, null=True, blank=True)  # noqa: DJ001 - ERD: null
    status = models.CharField(max_length=12, choices=UserStatus.choices)
    permanent_branch = models.ForeignKey(
        "branches.Branch", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    deactivated_at = models.DateTimeField(null=True, blank=True)
    # OQ-23 C5: set when a Super Admin creates or resets the user; cleared on password change.
    must_change_password = models.BooleanField(default=False)

    USERNAME_FIELD = "login_id"
    REQUIRED_FIELDS = ["full_name", "phone"]

    objects = UserManager()

    class Meta:
        indexes = [models.Index(fields=["status"], name="accounts_user_status_idx")]
        constraints = [
            models.CheckConstraint(
                condition=Q(login_id__regex=r"^(SA|USR)-[0-9]{4,}$"),
                name="accounts_user_login_id_format",
            ),
            models.CheckConstraint(
                condition=Q(status__in=[s.value for s in UserStatus]),
                name="accounts_user_status_valid",
            ),
        ]

    def __str__(self) -> str:
        return str(self.login_id)

    @property
    def is_active(self) -> bool:  # type: ignore[override]
        """Only ``active`` users can log in (BE s2)."""
        return bool(self.status == UserStatus.ACTIVE)

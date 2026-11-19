"""The custom user model (B2.2, ERD s3.1). ``AUTH_USER_MODEL = "accounts.User"``."""

from typing import Any, NoReturn

from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.db import models
from django.db.models import Q

from accounts.ids import next_login_id
from eqp4l.db import AuditFields


class UserStatus(models.TextChoices):
    PENDING = "pending"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    DEACTIVATED = "deactivated"


class UserManager(BaseUserManager["User"]):
    def create_user(
        self,
        *,
        full_name: str,
        phone: str,
        password: str | None,
        super_admin: bool = False,
        email: str | None = None,
        status: str = UserStatus.ACTIVE,
        **extra: Any,
    ) -> "User":
        """Create a user with a freshly generated, immutable login ID.

        Rule: the ID prefix (``SA`` or ``USR``) is fixed here by the user's first role and
        never changes (ERD s3.1, E8). The audit event ``user.created`` is written by the
        user-management service (B2.4), not here.
        """
        user = self.model(
            login_id=next_login_id(super_admin=super_admin),
            full_name=full_name,
            phone=phone,
            email=email,
            status=status,
            **extra,
        )
        user.set_password(password)
        user.save(using=self._db)
        return user


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
    must_change_password = models.BooleanField(default=False, db_default=False)

    USERNAME_FIELD = "login_id"
    REQUIRED_FIELDS = ["full_name", "phone"]

    # ERD s3.1: the first user is seeded, so only here the audit users may be null.
    created_by = models.ForeignKey(  # type: ignore[assignment]
        "self", null=True, blank=True, editable=False, on_delete=models.PROTECT, related_name="+"
    )
    updated_by = models.ForeignKey(  # type: ignore[assignment]
        "self", null=True, blank=True, editable=False, on_delete=models.PROTECT, related_name="+"
    )

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

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        # The ID as loaded (or first given), so a later change is caught in save().
        self._loaded_login_id: str | None = self.__dict__.get("login_id")

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Refuse a missing or changed login ID (the database trigger also rejects a change)."""
        if self._state.adding:
            if not self.login_id:
                raise ValueError(
                    "A user needs a login_id; create users with User.objects.create_user()."
                )
        elif getattr(self, "_loaded_login_id", self.login_id) != self.login_id:
            raise ValueError("login_id is immutable and cannot be changed.")
        super().save(*args, **kwargs)
        self._loaded_login_id = self.login_id

    def delete(self, *args: Any, **kwargs: Any) -> NoReturn:
        raise ValueError("Users are never deleted; deactivate them instead (ERD s2).")

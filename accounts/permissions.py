from typing import Any

from rest_framework.permissions import BasePermission
from rest_framework.request import Request


class IsActiveAccount(BasePermission):
    """Logged in with an account that may hold a session (suspended and deactivated never can)."""

    def has_permission(self, request: Request, view: Any) -> bool:
        user = request.user
        return bool(user and user.is_authenticated and user.is_active)


class PasswordChangeNotRequired(BasePermission):
    """C5: until the one-time password is changed, only /auth/me, /password, /logout, /csrf are open."""

    code = "password_change_required"
    message = "You must change your one-time password before doing anything else."

    def has_permission(self, request: Request, view: Any) -> bool:
        return not getattr(request.user, "must_change_password", False)

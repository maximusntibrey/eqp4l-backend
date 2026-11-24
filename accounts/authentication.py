from rest_framework.authentication import SessionAuthentication
from rest_framework.request import Request


class SessionAuth(SessionAuthentication):
    """Session cookie auth. The header makes a missing login answer 401 (not 403), as the contract says."""

    def authenticate_header(self, request: Request) -> str:
        return "Session"

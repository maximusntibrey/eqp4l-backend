"""Describes the session cookie auth in the generated OpenAPI document (contract: sessionAuth)."""

from typing import Any

from drf_spectacular.extensions import OpenApiAuthenticationExtension


class SessionAuthScheme(OpenApiAuthenticationExtension):
    target_class = "accounts.authentication.SessionAuth"
    name = "sessionAuth"

    def get_security_definition(self, auto_schema: Any) -> dict[str, str]:
        return {"type": "apiKey", "in": "cookie", "name": "sessionid"}

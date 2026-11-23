"""The one error format (contract `Error`): {code, message, errors: [{field, message}]}."""

from typing import Any

from django.http import HttpRequest, JsonResponse
from rest_framework import exceptions
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

CODE_BY_STATUS = {
    400: "parse_error",
    401: "not_authenticated",
    403: "permission_denied",
    404: "not_found",
    405: "method_not_allowed",
    415: "unsupported_media_type",
    429: "rate_limited",
}


class ApiError(Exception):
    """A rule refusal with a stable code, a plain message and optionally the field at fault."""

    def __init__(
        self,
        status: int,
        code: str,
        message: str,
        field: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status, self.code, self.message, self.field = status, code, message, field
        self.headers = headers or {}


def error_body(code: str, message: str, errors: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {"code": code, "message": message, "errors": errors or []}


def flatten(data: Any, prefix: str = "") -> list[dict[str, Any]]:
    """Turn DRF validation errors into [{field, message}] with dotted field names."""
    if isinstance(data, dict):
        out: list[dict[str, Any]] = []
        for key, value in data.items():
            path = prefix if key == "non_field_errors" else f"{prefix}.{key}" if prefix else str(key)
            out += flatten(value, path)
        return out
    if isinstance(data, list):
        out = []
        for index, value in enumerate(data):
            if isinstance(value, (dict, list)):
                out += flatten(value, f"{prefix}.{index}" if prefix else str(index))
            elif value:
                out.append({"field": prefix or None, "message": str(value)})
        return out
    return [{"field": prefix or None, "message": str(data)}]


def exception_handler(exc: Exception, context: dict[str, Any]) -> Response | None:
    if isinstance(exc, ApiError):
        errors = [{"field": exc.field, "message": exc.message}]
        return Response(error_body(exc.code, exc.message, errors), status=exc.status, headers=exc.headers)
    response = drf_exception_handler(exc, context)
    if response is None:
        return None
    if isinstance(exc, exceptions.ValidationError):
        response.data = error_body("validation_error", "Check the highlighted fields.", flatten(exc.detail))
        return response
    detail = response.data.get("detail", "") if isinstance(response.data, dict) else ""
    code = CODE_BY_STATUS.get(response.status_code, "error")
    if isinstance(exc, exceptions.PermissionDenied):
        code = getattr(exc.detail, "code", code)
        if str(exc.detail).startswith("CSRF"):
            code = "csrf_failed"
    response.data = error_body(code, str(detail))
    return response


def csrf_failure(request: HttpRequest, reason: str = "") -> JsonResponse:
    """Django's CSRF failure view, answering in the standard error format."""
    body = error_body("csrf_failed", "Security token missing or wrong. Reload the page and try again.")
    return JsonResponse(body, status=403)

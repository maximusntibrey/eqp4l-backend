"""Idempotency-Key for state-changing endpoints (every POST, PUT, PATCH except login, logout, password).

Same key and body by the same user on the same URL: the first response again, no second change.
Same key with another body: 409 `idempotency_conflict`. Keys are stored per (actor, scope, key), so one
user can never read another's stored response (FIX-1). A refused request stores nothing: a retry runs.
"""

import base64
import hashlib
import hmac
import json
import uuid
from collections.abc import Callable
from typing import Any, cast

from django.conf import settings
from django.core.files.uploadedfile import UploadedFile
from django.db import transaction
from rest_framework.request import Request
from rest_framework.response import Response

from accounts.models import User
from config.errors import ApiError
from stock_ledger.models import IdempotencyKey

HEADER = "Idempotency-Key"


def request_key(request: Request) -> uuid.UUID:
    raw = request.headers.get(HEADER, "")
    try:
        return uuid.UUID(raw)
    except ValueError:
        raise ApiError(
            400, "validation_error", "Send a valid Idempotency-Key header (a UUID).", HEADER
        ) from None


def derive_one_time_password(request: Request) -> str:
    """A one-time password derived from the key, so a replay can show it again without storing it.

    HMAC of (user, URL, key) under SECRET_KEY: 12 characters, 72 bits. Never stored, never logged.
    """
    message = f"otp:{request.user.pk}:{request.path}:{request_key(request)}".encode()
    digest = hmac.new(settings.SECRET_KEY.encode(), message, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest[:9]).decode()


def _json_default(value: Any) -> str:
    """Uploaded files count by content, not by name, so the same key with another image is a conflict."""
    if isinstance(value, UploadedFile):
        digest = hashlib.sha256()
        for chunk in value.chunks():
            digest.update(chunk)
        value.seek(0)
        return f"file:{digest.hexdigest()}"
    return str(value)


def idempotent(
    request: Request,
    work: Callable[[], tuple[int, dict[str, Any]]],
    *,
    secrets: Callable[[], dict[str, Any]] | None = None,
) -> Response:
    """Run `work` once per key. `secrets()` is merged into the response but never stored."""
    key = request_key(request)
    scope = f"{request.method} {request.path}"[:80]
    body_hash = hashlib.sha256(
        json.dumps(request.data, sort_keys=True, default=_json_default).encode()
    ).hexdigest()
    with transaction.atomic():
        # The unique (actor, scope, key) index makes a concurrent duplicate wait here for the first commit.
        row, created = IdempotencyKey.objects.get_or_create(
            actor=cast(User, request.user), scope=scope, key=key, defaults={"request_hash": body_hash}
        )
        if not created:
            if row.request_hash != body_hash:
                raise ApiError(
                    409,
                    "idempotency_conflict",
                    "This Idempotency-Key was already used for a different request.",
                )
            status, body = row.response_status or 200, dict(row.response_body or {})
        else:
            status, body = work()
            row.response_status, row.response_body = status, body
            row.save(update_fields=["response_status", "response_body"])
    if secrets is not None:
        body = {**body, **secrets()}
    return Response(body, status=status)

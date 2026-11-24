"""Small helpers for the B3 endpoint tests."""

import uuid
from typing import Any

from rest_framework.test import APIClient

from tests.conftest import login


def client_as(user: Any) -> APIClient:
    """A client logged in through the real endpoint."""
    client = APIClient()
    response = login(client, user)
    assert response.status_code == 200, response.content
    return client


def call(
    client: APIClient,
    method: str,
    url: str,
    body: Any = None,
    *,
    key: str | uuid.UUID | bool | None = None,
    **extra: Any,
) -> Any:
    """Send a request. Unsafe methods get a fresh Idempotency-Key unless `key` is given (False: none)."""
    method = method.upper()
    if method == "GET":
        return client.get(url, body, **extra)
    if key is not False:
        extra["HTTP_IDEMPOTENCY_KEY"] = str(uuid.uuid4() if key is None else key)
    return getattr(client, method.lower())(url, body, format="json", **extra)

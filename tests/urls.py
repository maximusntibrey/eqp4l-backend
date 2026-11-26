"""Test-only URLconf: the real routes plus probe views for the default and per-action permissions."""

from typing import Any

from django.urls import include, path
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from roles.permissions import ACTIONS, action_permissions


class DefaultProbe(APIView):
    """Inherits the project's default permissions (logged in, no pending password change)."""

    def get(self, request: Request) -> Response:
        return Response({"ok": True})

    def post(self, request: Request) -> Response:
        return Response({"ok": True})


def action_probe(action: str) -> Any:
    class Probe(APIView):
        permission_classes = action_permissions(action)

        def get(self, request: Request) -> Response:
            return Response({"ok": True})

    return Probe.as_view()


urlpatterns = [
    path("", include("config.urls")),
    path("probe/default/", DefaultProbe.as_view()),
    *[path(f"probe/action/{a}/", action_probe(a)) for a in ACTIONS],
]

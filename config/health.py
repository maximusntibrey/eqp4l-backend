"""Liveness/readiness check: the app is up and the database answers."""

import logging

from django.db import DatabaseError, connection
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers, status
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response

logger = logging.getLogger(__name__)


class HealthSerializer(serializers.Serializer[object]):
    status = serializers.CharField()
    database = serializers.CharField()


@extend_schema(
    responses={200: HealthSerializer, 503: OpenApiResponse(HealthSerializer, description="Database down")},
    auth=[],
)
@api_view(["GET"])
@authentication_classes([])
@permission_classes([AllowAny])
def health(request: Request) -> Response:
    """Return 200 when the app and database are up, 503 when the database is not."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except DatabaseError:
        logger.exception("health check: database unavailable")
        return Response(
            {"status": "error", "database": "unavailable"}, status=status.HTTP_503_SERVICE_UNAVAILABLE
        )
    return Response({"status": "ok", "database": "ok"})

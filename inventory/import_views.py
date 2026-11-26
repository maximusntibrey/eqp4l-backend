"""CSV import API (B6.4; PERMISSION_TABLE rows 19, 20): Super Admin and Warehouse Admin only."""

from typing import Any, cast

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import serializers
from rest_framework.parsers import MultiPartParser
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import User
from accounts.serializers import ErrorSerializer
from config.idempotency import idempotent, operation_id_for
from inventory import imports
from roles.permissions import action_permissions

ERROR = OpenApiResponse(ErrorSerializer)
IDEMPOTENCY = OpenApiParameter("Idempotency-Key", OpenApiTypes.UUID, OpenApiParameter.HEADER, required=True)


class ImportErrorSerializer(serializers.Serializer[object]):
    row = serializers.IntegerField(help_text="CSV row number; the header is row 1.")
    field = serializers.CharField(allow_null=True)
    message = serializers.CharField()


class ImportReportSerializer(serializers.Serializer[object]):
    dry_run = serializers.BooleanField()
    committed = serializers.BooleanField()
    batch_reference = serializers.CharField(allow_null=True)
    location_id = serializers.IntegerField()
    rows = serializers.IntegerField()
    items_created = serializers.IntegerField()
    items_existing = serializers.IntegerField()
    opening_quantity_total = serializers.IntegerField()
    errors = ImportErrorSerializer(many=True)  # type: ignore[assignment]  # the contract's key


class ImportRequestSerializer(serializers.Serializer[object]):
    file = serializers.FileField()
    # A string, not a BooleanField: an absent form field must never read as "false" and commit.
    dry_run = serializers.ChoiceField(choices=["true", "false"])
    location_id = serializers.IntegerField(required=False, min_value=1)


class ItemImportView(APIView):
    permission_classes = action_permissions("items.import")  # SA, WA (rows 19, 20)
    parser_classes = [MultiPartParser]

    @extend_schema(
        operation_id="itemImportsCreate",
        tags=["imports"],
        parameters=[IDEMPOTENCY],
        request={"multipart/form-data": ImportRequestSerializer},
        responses={200: ImportReportSerializer, 400: ERROR, 401: ERROR, 403: ERROR, 409: ERROR, 413: ERROR},
    )
    def post(self, request: Request) -> Response:
        data = ImportRequestSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        operation_id = operation_id_for(request)

        def work() -> tuple[int, dict[str, Any]]:
            report = imports.import_items(
                request._request,
                cast(User, request.user),
                upload=data.validated_data["file"],
                location_id=data.validated_data.get("location_id"),
                dry_run=data.validated_data["dry_run"] == "true",
                operation_id=operation_id,
            )
            return 200, report

        return idempotent(request, work)

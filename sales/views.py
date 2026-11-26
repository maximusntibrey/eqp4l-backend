"""Sales API (B6.1, B6.2, B6.5; PERMISSION_TABLE rows 36, 38, 39).

Plain sale payloads never carry cost. The cost snapshot (4 dp in the DB) is shown at 2 dp only by the
Super Admin-only `/costed-sales/` operations (table row 48, OQ-31).
"""

from datetime import date, datetime, time, timedelta
from typing import Any, cast
from zoneinfo import ZoneInfo

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import generics, serializers
from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import User
from accounts.serializers import ErrorSerializer
from branches.models import Location
from config.errors import ApiError
from config.idempotency import idempotent, operation_id_for
from inventory.services import money
from inventory.stock_views import visible_location
from roles import constants as c
from roles.permissions import action_permissions
from roles.services import active_role
from sales import services
from sales.models import Sale, SaleCancellation, SaleLine, SaleStatus

ERROR = OpenApiResponse(ErrorSerializer)
IDEMPOTENCY = OpenApiParameter("Idempotency-Key", OpenApiTypes.UUID, OpenApiParameter.HEADER, required=True)
ACCRA = ZoneInfo("Africa/Accra")
PAYMENT_CODES = ["cash", "mobile_money", "card"]


class SaleLineWriteSerializer(serializers.Serializer[object]):
    item_id = serializers.IntegerField(min_value=1)
    quantity = serializers.IntegerField(min_value=1, max_value=1_000_000)


class SaleCreateSerializer(serializers.Serializer[object]):
    payment_method = serializers.CharField(max_length=30)  # a configurable code, checked in the service
    lines = SaleLineWriteSerializer(many=True, allow_empty=False, max_length=200)  # type: ignore[call-arg]


class SaleCancelSerializer(serializers.Serializer[object]):
    reason = serializers.CharField(max_length=1000)  # trimmed and non-blank by default


class SaleLineSerializer(serializers.ModelSerializer[SaleLine]):
    sku = serializers.CharField(source="item.sku")
    item_name = serializers.CharField(source="item.name")
    unit_price = serializers.SerializerMethodField()
    line_total = serializers.SerializerMethodField()

    class Meta:
        model = SaleLine
        fields = ["id", "item_id", "sku", "item_name", "quantity", "unit_price", "line_total"]

    def get_unit_price(self, obj: SaleLine) -> str | None:
        return money(obj.unit_price)

    def get_line_total(self, obj: SaleLine) -> str | None:
        return money(obj.line_total)


class CostedSaleLineSerializer(SaleLineSerializer):
    unit_cost = serializers.SerializerMethodField()

    class Meta(SaleLineSerializer.Meta):
        fields = [*SaleLineSerializer.Meta.fields, "unit_cost"]

    def get_unit_cost(self, obj: SaleLine) -> str | None:
        return money(obj.unit_cost_snapshot)  # 4 dp in the DB, 2 dp in the API


class SaleCancellationSerializer(serializers.ModelSerializer[SaleCancellation]):
    cancelled_by = serializers.CharField(source="cancelled_by.login_id")

    class Meta:
        model = SaleCancellation
        fields = ["reason", "cancelled_by", "cancelled_role", "cancelled_at"]


class SaleBranchSerializer(serializers.ModelSerializer[Location]):
    class Meta:
        model = Location
        fields = ["id", "kind", "code", "name", "is_active"]


class SaleSerializer(serializers.ModelSerializer[Sale]):
    location = SaleBranchSerializer()
    staff = serializers.CharField(source="staff.login_id")
    payment_method = serializers.CharField(source="payment_method.code")
    status = serializers.ChoiceField(choices=SaleStatus.choices)
    total = serializers.SerializerMethodField()
    lines = SaleLineSerializer(many=True)
    cancellation = SaleCancellationSerializer(allow_null=True)

    class Meta:
        model = Sale
        fields = [
            "id",
            "reference",
            "location",
            "staff",
            "status",
            "payment_method",
            "total",
            "sold_at",
            "lines",
            "cancellation",
        ]

    def get_total(self, obj: Sale) -> str | None:
        return money(obj.total)


class CostedSaleSerializer(SaleSerializer):
    lines = CostedSaleLineSerializer(many=True)


class SaleQuerySerializer(serializers.Serializer[object]):
    branch = serializers.IntegerField(required=False, min_value=1)
    status = serializers.ChoiceField(choices=SaleStatus.choices, required=False)
    payment_method = serializers.ChoiceField(choices=PAYMENT_CODES, required=False)
    item_id = serializers.IntegerField(required=False, min_value=1)
    staff_id = serializers.IntegerField(required=False, min_value=1)
    date_from = serializers.DateField(required=False)
    date_to = serializers.DateField(required=False)


def _day_start(day: date) -> datetime:
    return datetime.combine(day, time.min, tzinfo=ACCRA)


def _in_scope(request: Request) -> Any:
    """Sales the caller may see: SA every branch (optional `branch`), BA and FS their own branch only."""
    qs = services.sale_queryset()
    location = visible_location(request, None)
    return qs.filter(location_id=location) if location is not None else qs


def _filtered_sales(request: Request) -> Any:
    query = SaleQuerySerializer(data=request.query_params)
    query.is_valid(raise_exception=True)
    params = query.validated_data
    location = visible_location(request, params.get("branch"))
    qs = services.sale_queryset().order_by("-id")
    if location is not None:
        qs = qs.filter(location_id=location)
    for field, lookup in (
        ("status", "status"),
        ("payment_method", "payment_method__code"),
        ("item_id", "lines__item_id"),
        ("staff_id", "staff_id"),
    ):
        if field in params:
            qs = qs.filter(**{lookup: params[field]})
    if "date_from" in params:
        qs = qs.filter(sold_at__gte=_day_start(params["date_from"]))
    if "date_to" in params:  # the whole last day, Accra time
        qs = qs.filter(sold_at__lt=_day_start(params["date_to"] + timedelta(days=1)))
    return qs


class SaleListCreateView(generics.GenericAPIView[Sale]):
    filter_backends = ()
    serializer_class = SaleSerializer
    permission_classes = action_permissions("sales.record")  # SA, BA, FS (rows 36, 38)

    @extend_schema(
        operation_id="salesList",
        tags=["sales"],
        parameters=[SaleQuerySerializer],
        responses={200: SaleSerializer(many=True), 400: ERROR, 401: ERROR, 403: ERROR},
    )
    def get(self, request: Request) -> Response:
        qs = _filtered_sales(request)
        page = self.paginate_queryset(qs)
        return self.get_paginated_response(self.get_serializer(page, many=True).data)

    @extend_schema(
        operation_id="salesCreate",
        tags=["sales"],
        parameters=[IDEMPOTENCY],
        request=SaleCreateSerializer,
        responses={201: SaleSerializer, 400: ERROR, 401: ERROR, 403: ERROR, 409: ERROR},
    )
    def post(self, request: Request) -> Response:
        data = SaleCreateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        operation_id = operation_id_for(request)

        def work() -> tuple[int, dict[str, Any]]:
            sale = services.record_sale(
                request._request, cast(User, request.user), data.validated_data, operation_id
            )
            return 201, dict(SaleSerializer(services.sale_queryset().get(pk=sale.pk)).data)

        return idempotent(request, work)


def _own_sale_or_404(request: Request, sale_id: int) -> Sale:
    sale = _in_scope(request).filter(pk=sale_id).first()
    if sale is None:  # another branch's sale looks the same as a missing one (OQ-30)
        raise ApiError(404, "not_found", "No such sale.")
    return cast(Sale, sale)


class SaleDetailView(APIView):
    permission_classes = action_permissions("sales.record")

    @extend_schema(
        operation_id="salesRead",
        tags=["sales"],
        parameters=[OpenApiParameter("id", OpenApiTypes.INT, OpenApiParameter.PATH)],
        responses={200: SaleSerializer, 401: ERROR, 403: ERROR, 404: ERROR},
    )
    def get(self, request: Request, id: int) -> Response:
        return Response(SaleSerializer(_own_sale_or_404(request, id)).data)


class SaleCancelView(APIView):
    permission_classes = action_permissions("sales.cancel")  # SA, BA (row 39); BA own branch in the service

    @extend_schema(
        operation_id="salesCancel",
        tags=["sales"],
        parameters=[OpenApiParameter("id", OpenApiTypes.INT, OpenApiParameter.PATH), IDEMPOTENCY],
        request=SaleCancelSerializer,
        responses={200: SaleSerializer, 400: ERROR, 401: ERROR, 403: ERROR, 404: ERROR, 409: ERROR},
    )
    def post(self, request: Request, id: int) -> Response:
        data = SaleCancelSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        operation_id = operation_id_for(request)

        def work() -> tuple[int, dict[str, Any]]:
            sale = services.cancel_sale(
                request._request, cast(User, request.user), id, data.validated_data["reason"], operation_id
            )
            return 200, dict(SaleSerializer(services.sale_queryset().get(pk=sale.pk)).data)

        return idempotent(request, work)


class SuperAdminOnly(BasePermission):
    """Table row 48: the sale cost snapshot is for the Super Admin only (WA has no sales access)."""

    def has_permission(self, request: Request, view: Any) -> bool:
        return active_role(cast(User, request.user)) == c.SUPER_ADMIN


class CostedSaleListView(generics.GenericAPIView[Sale]):
    filter_backends = ()
    serializer_class = CostedSaleSerializer
    permission_classes = [*action_permissions("items.view_cost"), SuperAdminOnly]

    @extend_schema(
        operation_id="costedSalesList",
        tags=["sales"],
        parameters=[SaleQuerySerializer],
        responses={200: CostedSaleSerializer(many=True), 400: ERROR, 401: ERROR, 403: ERROR},
    )
    def get(self, request: Request) -> Response:
        page = self.paginate_queryset(_filtered_sales(request))
        return self.get_paginated_response(self.get_serializer(page, many=True).data)


class CostedSaleDetailView(APIView):
    permission_classes = [*action_permissions("items.view_cost"), SuperAdminOnly]

    @extend_schema(
        operation_id="costedSalesRead",
        tags=["sales"],
        parameters=[OpenApiParameter("id", OpenApiTypes.INT, OpenApiParameter.PATH)],
        responses={200: CostedSaleSerializer, 401: ERROR, 403: ERROR, 404: ERROR},
    )
    def get(self, request: Request, id: int) -> Response:
        return Response(CostedSaleSerializer(_own_sale_or_404(request, id)).data)

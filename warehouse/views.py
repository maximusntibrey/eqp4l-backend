"""Goods receipt API (B5.1; PERMISSION_TABLE rows 25 and 27): Super Admin and Warehouse Admin only."""

from typing import Any, cast

from django.shortcuts import get_object_or_404
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import generics, serializers
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import User
from accounts.serializers import ErrorSerializer
from config.idempotency import idempotent, operation_id_for
from inventory.services import money
from roles.permissions import action_permissions
from warehouse import services
from warehouse.models import GoodsReceipt, GoodsReceiptLine

ERROR = OpenApiResponse(ErrorSerializer)
IDEMPOTENCY = OpenApiParameter("Idempotency-Key", OpenApiTypes.UUID, OpenApiParameter.HEADER, required=True)


class ReceiptLineWriteSerializer(serializers.Serializer[object]):
    item_id = serializers.IntegerField(min_value=1)
    quantity = serializers.IntegerField(min_value=1, max_value=1_000_000)
    unit_cost = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=0)


class GoodsReceiptCreateSerializer(serializers.Serializer[object]):
    supplier_name = serializers.CharField(max_length=200)  # trimmed and non-blank by default
    notes = serializers.CharField(max_length=1000, required=False, allow_blank=True)
    lines = ReceiptLineWriteSerializer(many=True, allow_empty=False)


class ReceiptLineSerializer(serializers.ModelSerializer[GoodsReceiptLine]):
    sku = serializers.CharField(source="item.sku")
    item_name = serializers.CharField(source="item.name")
    unit_cost = serializers.SerializerMethodField()

    class Meta:
        model = GoodsReceiptLine
        fields = ["id", "item_id", "sku", "item_name", "quantity", "unit_cost"]

    def get_unit_cost(self, obj: GoodsReceiptLine) -> str | None:
        return money(obj.unit_cost)


class GoodsReceiptSerializer(serializers.ModelSerializer[GoodsReceipt]):
    location_id = serializers.IntegerField()
    received_by = serializers.CharField(source="received_by.login_id")
    lines = ReceiptLineSerializer(many=True)

    class Meta:
        model = GoodsReceipt
        fields = [
            "id",
            "reference",
            "location_id",
            "supplier_name",
            "notes",
            "lines",
            "received_at",
            "received_by",
        ]


class ReceiptQuerySerializer(serializers.Serializer[object]):
    supplier_name = serializers.CharField(required=False, allow_blank=True)


def _queryset() -> Any:
    return GoodsReceipt.objects.select_related("received_by").prefetch_related("lines__item")


class GoodsReceiptListCreateView(generics.GenericAPIView[GoodsReceipt]):
    filter_backends = ()
    serializer_class = GoodsReceiptSerializer
    permission_classes = action_permissions("goods_receipts.manage")  # SA and WA, read and write

    @extend_schema(
        operation_id="goodsReceiptsList",
        tags=["goods-receipts"],
        parameters=[ReceiptQuerySerializer],
        responses={200: GoodsReceiptSerializer(many=True), 401: ERROR, 403: ERROR},
    )
    def get(self, request: Request) -> Response:
        query = ReceiptQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        qs = _queryset().order_by("-id")
        if name := query.validated_data.get("supplier_name", "").strip():
            qs = qs.filter(supplier_name__icontains=name)
        page = self.paginate_queryset(qs)
        return self.get_paginated_response(self.get_serializer(page, many=True).data)

    @extend_schema(
        operation_id="goodsReceiptsCreate",
        tags=["goods-receipts"],
        parameters=[IDEMPOTENCY],
        request=GoodsReceiptCreateSerializer,
        responses={201: GoodsReceiptSerializer, 400: ERROR, 401: ERROR, 403: ERROR, 409: ERROR},
    )
    def post(self, request: Request) -> Response:
        data = GoodsReceiptCreateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        operation_id = operation_id_for(request)

        def work() -> tuple[int, dict[str, Any]]:
            receipt = services.create_receipt(
                request._request, cast(User, request.user), data.validated_data, operation_id
            )
            return 201, dict(GoodsReceiptSerializer(_queryset().get(pk=receipt.pk)).data)

        return idempotent(request, work)


class GoodsReceiptDetailView(APIView):
    permission_classes = action_permissions("goods_receipts.manage")

    @extend_schema(
        operation_id="goodsReceiptsRead",
        tags=["goods-receipts"],
        parameters=[OpenApiParameter("id", OpenApiTypes.INT, OpenApiParameter.PATH)],
        responses={200: GoodsReceiptSerializer, 401: ERROR, 403: ERROR, 404: ERROR},
    )
    def get(self, request: Request, id: int) -> Response:
        return Response(GoodsReceiptSerializer(get_object_or_404(_queryset(), pk=id)).data)

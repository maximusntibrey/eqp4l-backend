"""Thin views for the item and brand endpoints (B4.1, B4.2): validate, call the service, serialise."""

from typing import Any, cast

from django.db.models import Prefetch
from django.shortcuts import get_object_or_404
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import generics
from rest_framework.parsers import MultiPartParser
from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import User
from accounts.serializers import ErrorSerializer
from config.errors import ApiError
from config.idempotency import idempotent
from inventory import services
from inventory.catalog import definitions_for
from inventory.models import Brand, Category, Item, Subtype
from inventory.serializers import (
    BrandSerializer,
    BrandWriteSerializer,
    CategorySerializer,
    FieldDefinitionSerializer,
    ImageSerializer,
    ItemQuerySerializer,
    ItemSerializer,
    ItemWithCostAndWarningsSerializer,
    ItemWithCostSerializer,
    ItemWriteSerializer,
    StatusSerializer,
)
from roles.permissions import action_permissions

ERROR = OpenApiResponse(ErrorSerializer)
IDEMPOTENCY = OpenApiParameter("Idempotency-Key", OpenApiTypes.UUID, OpenApiParameter.HEADER, required=True)
WRITE_ERRORS = {400: ERROR, 401: ERROR, 403: ERROR, 404: ERROR, 409: ERROR}
CREATE_ERRORS = {400: ERROR, 401: ERROR, 403: ERROR, 409: ERROR}


def _by_method(request: Request, read: str, write: str) -> list[BasePermission]:
    action = read if request.method == "GET" else write
    return [p() for p in action_permissions(action)]


class CategoryListView(APIView):
    permission_classes = action_permissions("items.view")

    @extend_schema(
        operation_id="itemCategoriesList",
        tags=["items"],
        responses={200: CategorySerializer(many=True), 401: ERROR},
    )
    def get(self, request: Request) -> Response:
        categories = Category.objects.prefetch_related(
            Prefetch("subtypes", queryset=Subtype.objects.order_by("id"))
        ).order_by("id")
        return Response(CategorySerializer(categories, many=True).data)


class BrandListCreateView(APIView):
    def get_permissions(self) -> list[BasePermission]:
        return _by_method(self.request, "items.view", "items.manage")

    @extend_schema(
        operation_id="brandsList",
        tags=["items"],
        responses={200: BrandSerializer(many=True), 401: ERROR},
    )
    def get(self, request: Request) -> Response:
        return Response(BrandSerializer(Brand.objects.order_by("name"), many=True).data)

    @extend_schema(
        operation_id="brandsCreate",
        tags=["items"],
        parameters=[IDEMPOTENCY],
        request=BrandWriteSerializer,
        responses={201: BrandSerializer, **CREATE_ERRORS},
    )
    def post(self, request: Request) -> Response:
        data = BrandWriteSerializer(data=request.data)
        data.is_valid(raise_exception=True)

        def work() -> tuple[int, dict[str, Any]]:
            brand = services.save_brand(request._request, cast(User, request.user), data.validated_data)
            return 201, dict(BrandSerializer(brand).data)

        return idempotent(request, work)


class BrandDetailView(APIView):
    permission_classes = action_permissions("items.manage")

    @extend_schema(
        operation_id="brandsUpdate",
        tags=["items"],
        parameters=[IDEMPOTENCY],
        request=BrandWriteSerializer,
        responses={200: BrandSerializer, **WRITE_ERRORS},
    )
    def patch(self, request: Request, id: int) -> Response:
        data = BrandWriteSerializer(data=request.data, partial=True)
        data.is_valid(raise_exception=True)
        brand = get_object_or_404(Brand, pk=id)

        def work() -> tuple[int, dict[str, Any]]:
            saved = services.save_brand(
                request._request, cast(User, request.user), data.validated_data, brand
            )
            return 200, dict(BrandSerializer(saved).data)

        return idempotent(request, work)


class FieldDefinitionListView(APIView):
    permission_classes = action_permissions("items.view")

    @extend_schema(
        operation_id="itemFieldDefinitionsList",
        tags=["items"],
        parameters=[OpenApiParameter("category_id", OpenApiTypes.INT, required=True)],
        responses={200: FieldDefinitionSerializer(many=True), 400: ERROR, 401: ERROR},
    )
    def get(self, request: Request) -> Response:
        raw = request.query_params.get("category_id", "")
        category = Category.objects.filter(pk=raw).first() if raw.isdigit() else None
        if category is None:
            raise ApiError(400, "validation_error", "Choose a category.", "category_id")
        return Response(FieldDefinitionSerializer(definitions_for(category.name), many=True).data)


class _ItemListBase(generics.GenericAPIView[Item]):
    filter_backends = ()
    serializer_class = ItemSerializer

    def list_items(self, request: Request) -> Response:
        query = ItemQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        page = self.paginate_queryset(services.search_items(query.validated_data))
        return self.get_paginated_response(self.get_serializer(page, many=True).data)


class ItemListCreateView(_ItemListBase):
    def get_permissions(self) -> list[BasePermission]:
        return _by_method(self.request, "items.view", "items.manage")

    @extend_schema(
        operation_id="itemsList",
        tags=["items"],
        parameters=[ItemQuerySerializer],
        responses={200: ItemSerializer(many=True), 400: ERROR, 401: ERROR},
    )
    def get(self, request: Request) -> Response:
        return self.list_items(request)

    @extend_schema(
        operation_id="itemsCreate",
        tags=["items"],
        parameters=[IDEMPOTENCY],
        request=ItemWriteSerializer,
        responses={201: ItemWithCostAndWarningsSerializer, **CREATE_ERRORS},
    )
    def post(self, request: Request) -> Response:
        data = ItemWriteSerializer(data=request.data)
        data.is_valid(raise_exception=True)

        def work() -> tuple[int, dict[str, Any]]:
            item, warnings = services.create_item(
                request._request, cast(User, request.user), data.validated_data
            )
            return 201, _with_warnings(item.pk, warnings)

        return idempotent(request, work)


def _with_warnings(item_id: int, warnings: list[dict[str, Any]]) -> dict[str, Any]:
    item = services.item_queryset().get(pk=item_id)
    return {**ItemWithCostSerializer(item).data, "warnings": warnings}


class CostedItemListView(_ItemListBase):
    permission_classes = action_permissions("items.view_cost")
    serializer_class = ItemWithCostSerializer

    @extend_schema(
        operation_id="costedItemsList",
        tags=["items"],
        parameters=[ItemQuerySerializer],
        responses={200: ItemWithCostSerializer(many=True), 400: ERROR, 401: ERROR, 403: ERROR},
    )
    def get(self, request: Request) -> Response:
        return self.list_items(request)


class CostedItemDetailView(APIView):
    permission_classes = action_permissions("items.view_cost")

    @extend_schema(
        operation_id="costedItemsRead",
        tags=["items"],
        responses={200: ItemWithCostSerializer, 401: ERROR, 403: ERROR, 404: ERROR},
    )
    def get(self, request: Request, id: int) -> Response:
        return Response(ItemWithCostSerializer(get_object_or_404(services.item_queryset(), pk=id)).data)


class ItemDetailView(APIView):
    def get_permissions(self) -> list[BasePermission]:
        return _by_method(self.request, "items.view", "items.manage")

    @extend_schema(
        operation_id="itemsRead",
        tags=["items"],
        responses={200: ItemSerializer, 401: ERROR, 404: ERROR},
    )
    def get(self, request: Request, id: int) -> Response:
        return Response(ItemSerializer(get_object_or_404(services.item_queryset(), pk=id)).data)

    @extend_schema(
        operation_id="itemsUpdate",
        tags=["items"],
        parameters=[IDEMPOTENCY],
        request=ItemWriteSerializer,
        responses={200: ItemWithCostAndWarningsSerializer, **WRITE_ERRORS},
    )
    def patch(self, request: Request, id: int) -> Response:
        data = ItemWriteSerializer(data=request.data, partial=True)
        data.is_valid(raise_exception=True)

        def work() -> tuple[int, dict[str, Any]]:
            item, warnings = services.update_item(
                request._request, cast(User, request.user), id, data.validated_data
            )
            return 200, _with_warnings(item.pk, warnings)

        return idempotent(request, work)


class ItemStatusView(APIView):
    permission_classes = action_permissions("items.manage")

    @extend_schema(
        operation_id="itemsSetStatus",
        tags=["items"],
        parameters=[IDEMPOTENCY],
        request=StatusSerializer,
        responses={200: ItemWithCostSerializer, **WRITE_ERRORS},
    )
    def post(self, request: Request, id: int) -> Response:
        data = StatusSerializer(data=request.data)
        data.is_valid(raise_exception=True)

        def work() -> tuple[int, dict[str, Any]]:
            item = services.set_status(
                request._request, cast(User, request.user), id, data.validated_data["status"]
            )
            return 200, dict(ItemWithCostSerializer(services.item_queryset().get(pk=item.pk)).data)

        return idempotent(request, work)


class ItemImageView(APIView):
    permission_classes = action_permissions("items.manage")
    parser_classes = [MultiPartParser]

    @extend_schema(
        operation_id="itemsImageUpload",
        tags=["items"],
        parameters=[IDEMPOTENCY],
        request={"multipart/form-data": ImageSerializer},
        responses={200: ItemWithCostSerializer, 413: ERROR, **WRITE_ERRORS},
    )
    def put(self, request: Request, id: int) -> Response:
        data = ImageSerializer(data=request.data)
        data.is_valid(raise_exception=True)

        def work() -> tuple[int, dict[str, Any]]:
            item = services.store_image(
                request._request, cast(User, request.user), id, data.validated_data["image"]
            )
            return 200, dict(ItemWithCostSerializer(services.item_queryset().get(pk=item.pk)).data)

        return idempotent(request, work)

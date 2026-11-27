"""Stock query API (B4.4, PERMISSION_TABLE rows 21-22; contract /stock/, /costed-stock/, branch-availability).

Scope: SA sees every location; the central warehouse user every warehouse (no branches); WA their own
warehouse plus branch quantities (OQ-8), never another warehouse's rows (those only through
branch-availability: name and quantity); BA and FS only their working branch. Cost is read only through
`/costed-stock/`: SA every location, WA own warehouse rows only, others refused.
"""

from typing import Any, cast

from django.db.models import F, Q, QuerySet
from django.shortcuts import get_object_or_404
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import generics, serializers
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.me import working_branch
from accounts.models import User
from accounts.serializers import ErrorSerializer
from branches.models import Location, LocationKind
from config.errors import ApiError
from inventory.models import Item, StockBalance
from inventory.serializers import (
    BranchAvailabilitySerializer,
    StockBalanceSerializer,
    StockBalanceWithCostSerializer,
    StockMovementSerializer,
)
from roles import constants as c
from roles.permissions import action_permissions
from roles.services import active_role
from stock_ledger.models import MovementType, StockMovement

ERROR = OpenApiResponse(ErrorSerializer)


class StockQuerySerializer(serializers.Serializer[object]):
    location_id = serializers.IntegerField(required=False, min_value=1)
    item_id = serializers.IntegerField(required=False, min_value=1)
    q = serializers.CharField(required=False, allow_blank=True)


def visible_location(request: Request, location_id: int | None) -> int | None:
    """The one location the caller may see, or None for no single-location limit (SA, WA, central).

    WA and central are narrowed by `_by_role` instead."""
    user = cast(User, request.user)
    if active_role(user) in (c.SUPER_ADMIN, c.WAREHOUSE_ADMIN, c.CENTRAL_WAREHOUSE):
        return location_id
    own = working_branch(user, request._request)
    if own is None:
        raise ApiError(403, "wrong_branch", "Choose a working branch first.")
    if location_id is not None and location_id != own.pk:
        raise ApiError(403, "wrong_branch", "You can only see your own branch's stock.")
    return own.pk


def _by_role(request: Request, qs: QuerySet[Any]) -> QuerySet[Any]:
    """Rows the role may read: WA not another warehouse, central the warehouses only."""
    user = cast(User, request.user)
    role = active_role(user)
    if role == c.CENTRAL_WAREHOUSE:
        return qs.filter(location__kind=LocationKind.WAREHOUSE)
    if role == c.WAREHOUSE_ADMIN:
        return qs.filter(Q(location_id=user.permanent_location_id) | Q(location__kind=LocationKind.BRANCH))
    return qs


def scoped_balances(request: Request, location_id: int | None) -> QuerySet[StockBalance]:
    qs = StockBalance.objects.select_related("location", "item", "item__cost")
    location = visible_location(request, location_id)
    return _by_role(request, qs.filter(location_id=location) if location is not None else qs)


def _filtered(request: Request, costed: bool) -> QuerySet[StockBalance]:
    query = StockQuerySerializer(data=request.query_params)
    query.is_valid(raise_exception=True)
    params = query.validated_data
    qs = scoped_balances(request, params.get("location_id"))
    if costed and active_role(cast(User, request.user)) != c.SUPER_ADMIN:
        qs = qs.filter(location__kind=LocationKind.WAREHOUSE)  # no cost on branch quantities (OQ-8)
    if "item_id" in params:
        qs = qs.filter(item_id=params["item_id"])
    if params.get("q"):
        text = params["q"].strip()
        qs = qs.filter(
            Q(item__name__icontains=text)
            | Q(item__sku__icontains=text)
            | Q(item__brand__name__icontains=text)
            | Q(item__model_name__icontains=text)
        )
    return qs.order_by("location_id", "item_id")


class StockListView(generics.GenericAPIView[StockBalance]):
    filter_backends = ()
    permission_classes = action_permissions("stock.view")
    serializer_class = StockBalanceSerializer
    costed = False

    @extend_schema(
        operation_id="stockList",
        tags=["stock"],
        parameters=[StockQuerySerializer],
        responses={200: StockBalanceSerializer(many=True), 400: ERROR, 401: ERROR, 403: ERROR},
    )
    def get(self, request: Request) -> Response:
        page = self.paginate_queryset(_filtered(request, self.costed))
        return self.get_paginated_response(self.get_serializer(page, many=True).data)


class CostedStockListView(StockListView):
    permission_classes = action_permissions("items.view_cost")
    serializer_class = StockBalanceWithCostSerializer
    costed = True

    @extend_schema(
        operation_id="costedStockList",
        tags=["stock"],
        parameters=[StockQuerySerializer],
        responses={200: StockBalanceWithCostSerializer(many=True), 400: ERROR, 401: ERROR, 403: ERROR},
    )
    def get(self, request: Request) -> Response:
        return super().get(request)


class BranchAvailabilityView(APIView):
    permission_classes = action_permissions("stock.lookup_other_branches")

    @extend_schema(
        operation_id="itemsBranchAvailability",
        tags=["stock"],
        parameters=[OpenApiParameter("id", OpenApiTypes.INT, OpenApiParameter.PATH)],
        responses={200: BranchAvailabilitySerializer(many=True), 401: ERROR, 404: ERROR},
    )
    def get(self, request: Request, id: int) -> Response:
        """Name, kind and available quantity only, for every other active location (row 22). No cost or sales.

        Everyone sees the other branches; the other warehouses too, except Branch Admin and Front Staff.
        """
        item = get_object_or_404(Item, pk=id)
        user = cast(User, request.user)
        own = working_branch(user, request._request)
        kinds = [LocationKind.BRANCH]
        if active_role(user) not in (c.BRANCH_ADMIN, c.FRONT_STAFF):
            kinds.append(LocationKind.WAREHOUSE)
        branches = Location.objects.filter(kind__in=kinds, is_active=True).order_by("id")
        if own is not None:
            branches = branches.exclude(pk=own.pk)
        quantities = dict(
            StockBalance.objects.filter(item=item, location__in=branches).values_list(
                "location_id", F("on_hand") - F("reserved")
            )
        )
        rows = [
            {"branch_id": b.pk, "branch_name": b.name, "kind": b.kind, "quantity": quantities.get(b.pk, 0)}
            for b in branches
        ]
        return Response(BranchAvailabilitySerializer(rows, many=True).data)


class MovementQuerySerializer(serializers.Serializer[object]):
    location_id = serializers.IntegerField(required=False, min_value=1)
    item_id = serializers.IntegerField(required=False, min_value=1)
    movement_type = serializers.ChoiceField(choices=MovementType.choices, required=False)


class StockMovementListView(generics.GenericAPIView[StockMovement]):
    filter_backends = ()
    permission_classes = action_permissions("stock.view")
    serializer_class = StockMovementSerializer

    @extend_schema(
        operation_id="stockMovementsList",
        tags=["stock"],
        parameters=[MovementQuerySerializer],
        responses={200: StockMovementSerializer(many=True), 400: ERROR, 401: ERROR, 403: ERROR},
    )
    def get(self, request: Request) -> Response:
        query = MovementQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        params = query.validated_data
        location = visible_location(request, params.get("location_id"))
        qs = StockMovement.objects.select_related("location", "item", "actor").order_by("-id")
        if location is not None:
            qs = qs.filter(location_id=location)
        qs = _by_role(request, qs)  # type: ignore[assignment]
        for field in ("item_id", "movement_type"):
            if field in params:
                qs = qs.filter(**{field: params[field]})
        page = self.paginate_queryset(qs)
        return self.get_paginated_response(self.get_serializer(page, many=True).data)

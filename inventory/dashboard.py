"""Dashboard shell data (B3.4, PERMISSION_TABLE row 40; contract `Dashboard`).

Scope: SA all locations (waiting figure only for a chosen working branch), WA the warehouse, BA own branch;
Front Staff have no Home tab and are refused. Quantities only: no cost is ever read here (OQ-8, OVR 7).
"""

from typing import Any, cast

from django.db.models import F, IntegerField, Sum
from django.db.models.functions import Coalesce
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.me import working_branch
from accounts.models import User
from accounts.serializers import ROLE_CHOICES, BranchSerializer, ErrorSerializer
from audit.queries import scoped_events
from audit.views import ActivityEventSerializer
from branches.models import Location, LocationKind
from branches.services import branch_filter
from config.errors import ApiError
from inventory.models import Item, ItemStatus, StockBalance
from roles import constants as c
from roles.permissions import action_permissions
from roles.services import active_role
from transfers.models import Dispatch, DispatchStatus


class StockPerLocationSerializer(serializers.Serializer[object]):
    location_id = serializers.IntegerField()
    location_name = serializers.CharField()
    on_hand = serializers.IntegerField()
    available = serializers.IntegerField()


class LowStockSerializer(serializers.Serializer[object]):
    location_id = serializers.IntegerField()
    location_name = serializers.CharField()
    item_id = serializers.IntegerField()
    sku = serializers.CharField()
    item_name = serializers.CharField()
    available = serializers.IntegerField()
    reorder_level = serializers.IntegerField()


LIST_LIMIT = 10


class DashboardSerializer(serializers.Serializer[object]):
    role = serializers.ChoiceField(choices=ROLE_CHOICES)
    location = BranchSerializer(allow_null=True)
    waiting_dispatches = serializers.IntegerField()
    in_transit_dispatches = serializers.IntegerField()
    active_items = serializers.IntegerField()
    stock_per_location = StockPerLocationSerializer(many=True, required=False)
    low_stock_count = serializers.IntegerField()
    low_stock = LowStockSerializer(many=True)
    recent_activity = ActivityEventSerializer(many=True)


def dashboard_data(request: Request, user: User, branch_id: int | None = None) -> dict[str, Any]:
    """SA: all locations by default, or one branch with `branch_id`; WA: the warehouse; BA: own branch."""
    role = cast(str, active_role(user))
    is_sa = role == c.SUPER_ADMIN
    if is_sa:
        location = Location.objects.filter(pk=branch_id).first() if branch_id else None
        if branch_id and location is None:
            raise ApiError(400, "validation_error", "That branch does not exist.", "branch")
    else:
        location = working_branch(user, request._request)
    in_transit = Dispatch.objects.filter(status=DispatchStatus.IN_TRANSIT)
    if is_sa:
        to_view = in_transit.filter(destination_location=location) if location else in_transit
        waiting = to_view.count()
        in_transit_count = to_view.filter(origin_location__kind=LocationKind.WAREHOUSE).count()
    elif role == c.WAREHOUSE_ADMIN:
        waiting = 0
        in_transit_count = in_transit.filter(origin_location=location).count()  # own warehouse only
    else:  # BA: dispatches to the own branch; they are also what is waiting there
        waiting = in_transit_count = in_transit.filter(destination_location=location).count()
    data: dict[str, Any] = {
        "role": role,
        "location": location,
        "waiting_dispatches": waiting,
        "in_transit_dispatches": in_transit_count,
        "active_items": Item.objects.filter(status=ItemStatus.ACTIVE).count(),
    }
    # Low stock (B7.1): reorder level set and available at or below it, in the viewer's scope (row 40).
    low = StockBalance.objects.filter(
        reorder_level__isnull=False,
        reorder_level__gte=F("on_hand") - F("reserved"),
        item__status=ItemStatus.ACTIVE,
        location__is_active=True,
    ).select_related("location", "item")
    if location is not None:
        low = low.filter(location=location)
    elif not is_sa:  # an admin without a location sees nothing, never every location
        low = low.none()
    data["low_stock_count"] = low.count()
    data["low_stock"] = [
        {
            "location_id": b.location_id,
            "location_name": b.location.name,
            "item_id": b.item_id,
            "sku": b.item.sku,
            "item_name": b.item.name,
            "available": b.on_hand - b.reserved,
            "reorder_level": b.reorder_level,
        }
        for b in low.order_by("location_id", "item_id")[:LIST_LIMIT]
    ]
    data["recent_activity"] = list(
        scoped_events(user, request._request.session, location.pk if location else None)[:LIST_LIMIT]
    )
    if is_sa or role == c.WAREHOUSE_ADMIN:
        rows = Location.objects.filter(is_active=True)
        if is_sa and location is not None:
            rows = rows.filter(pk=location.pk)
        rows = rows.annotate(
            total_on_hand=Coalesce(Sum("balances__on_hand"), 0, output_field=IntegerField()),
            total_reserved=Coalesce(Sum("balances__reserved"), 0, output_field=IntegerField()),
        ).order_by("id")
        data["stock_per_location"] = [
            {
                "location_id": r.pk,
                "location_name": r.name,
                "on_hand": r.total_on_hand,
                "available": r.total_on_hand - r.total_reserved,
            }
            for r in rows
        ]
    return data


class DashboardQuerySerializer(serializers.Serializer[object]):
    branch = serializers.IntegerField(required=False, min_value=1)


class DashboardView(APIView):
    permission_classes = action_permissions("dashboard.view")

    @extend_schema(
        operation_id="dashboardRead",
        tags=["dashboard"],
        parameters=[DashboardQuerySerializer],
        responses={
            200: DashboardSerializer,
            400: OpenApiResponse(ErrorSerializer),
            401: OpenApiResponse(ErrorSerializer),
            403: OpenApiResponse(ErrorSerializer),
        },
    )
    def get(self, request: Request) -> Response:
        query = DashboardQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        user = cast(User, request.user)
        branch_id = branch_filter(user, query.validated_data.get("branch"))
        return Response(DashboardSerializer(dashboard_data(request, user, branch_id)).data)

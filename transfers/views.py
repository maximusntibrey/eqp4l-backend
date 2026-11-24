"""Dispatch API (B5.2 to B5.4; PERMISSION_TABLE rows 28 to 31).

Reads: SA and WA see every dispatch; BA and FS only those to their working branch (404 not_found
otherwise, like a missing id). Waiting (row 30): SA, BA, FS, never WA.
"""

from typing import Any, cast

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import generics, serializers
from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import User
from accounts.serializers import BranchSerializer, ErrorSerializer
from branches.models import Location, LocationKind
from config.errors import ApiError
from config.idempotency import idempotent, operation_id_for
from inventory.stock_views import visible_location
from roles import constants as c
from roles.permissions import action_permissions
from roles.services import active_role
from transfers import services
from transfers.models import Dispatch, DispatchLine, DispatchStatus

ERROR = OpenApiResponse(ErrorSerializer)
IDEMPOTENCY = OpenApiParameter("Idempotency-Key", OpenApiTypes.UUID, OpenApiParameter.HEADER, required=True)
ID_PARAM = OpenApiParameter("id", OpenApiTypes.INT, OpenApiParameter.PATH)


class DispatchLineWriteSerializer(serializers.Serializer[object]):
    item_id = serializers.IntegerField(min_value=1)
    quantity = serializers.IntegerField(min_value=1, max_value=1_000_000)


class DispatchCreateSerializer(serializers.Serializer[object]):
    destination_id = serializers.IntegerField(min_value=1)
    lines = DispatchLineWriteSerializer(many=True, allow_empty=False)


class ReceiveLineSerializer(serializers.Serializer[object]):
    line_id = serializers.IntegerField(min_value=1)
    qty_received = serializers.IntegerField(min_value=0, max_value=1_000_000)
    qty_accepted = serializers.IntegerField(min_value=0, max_value=1_000_000)
    line_note = serializers.CharField(max_length=500, required=False, allow_blank=True)


class DispatchReceiveSerializer(serializers.Serializer[object]):
    decision = serializers.ChoiceField(choices=["approve_all", "approve_partial", "reject"])
    note = serializers.CharField(max_length=1000, required=False, allow_blank=True)
    reason = serializers.CharField(max_length=1000, required=False, allow_blank=True)
    lines = ReceiveLineSerializer(many=True, required=False)


class DispatchLineSerializer(serializers.ModelSerializer[DispatchLine]):
    sku = serializers.CharField(source="item.sku")
    item_name = serializers.CharField(source="item.name")
    shortfall = serializers.SerializerMethodField()
    line_note = serializers.SerializerMethodField()

    class Meta:
        model = DispatchLine
        fields = [
            "id",
            "item_id",
            "sku",
            "item_name",
            "qty_sent",
            "qty_received",
            "qty_accepted",
            "qty_rejected",
            "shortfall",
            "line_note",
        ]

    def get_shortfall(self, obj: DispatchLine) -> int:
        return 0 if obj.qty_accepted is None else obj.qty_sent - obj.qty_accepted

    def get_line_note(self, obj: DispatchLine) -> str | None:
        return obj.line_note or None


class DispatchSerializer(serializers.ModelSerializer[Dispatch]):
    origin = BranchSerializer(source="origin_location")
    destination = BranchSerializer(source="destination_location")
    lines = DispatchLineSerializer(many=True)
    dispatched_by = serializers.CharField(source="dispatched_by.login_id")
    received_by = serializers.SerializerMethodField()
    receive_note = serializers.SerializerMethodField()
    has_open_discrepancy = serializers.SerializerMethodField()

    class Meta:
        model = Dispatch
        fields = [
            "id",
            "reference",
            "origin",
            "destination",
            "status",
            "lines",
            "dispatched_at",
            "dispatched_by",
            "received_at",
            "received_by",
            "receive_note",
            "has_open_discrepancy",
        ]

    def get_received_by(self, obj: Dispatch) -> str | None:
        return obj.received_by.login_id if obj.received_by else None

    def get_receive_note(self, obj: Dispatch) -> str | None:
        return obj.receive_note or None

    def get_has_open_discrepancy(self, obj: Dispatch) -> bool:
        """A shortfall not yet covered by resolutions (Sprint 2 adds the resolving endpoints)."""
        return any(
            ln.qty_accepted is not None
            and ln.qty_sent - ln.qty_accepted > sum(r.quantity for r in ln.resolutions.all())
            for ln in obj.lines.all()
        )


class DispatchQuerySerializer(serializers.Serializer[object]):
    status = serializers.ChoiceField(choices=DispatchStatus.choices, required=False)
    destination_id = serializers.IntegerField(min_value=1, required=False)


class WaitingQuerySerializer(serializers.Serializer[object]):
    branch_id = serializers.IntegerField(min_value=1, required=False)


class DispatchListCreateView(generics.GenericAPIView[Dispatch]):
    filter_backends = ()
    serializer_class = DispatchSerializer

    def get_permissions(self) -> list[BasePermission]:
        action = "dispatches.view" if self.request.method == "GET" else "dispatches.create"
        return [p() for p in action_permissions(action)]

    @extend_schema(
        operation_id="dispatchesList",
        tags=["dispatches"],
        parameters=[DispatchQuerySerializer],
        responses={200: DispatchSerializer(many=True), 400: ERROR, 401: ERROR, 403: ERROR},
    )
    def get(self, request: Request) -> Response:
        query = DispatchQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        params = query.validated_data
        qs = services.dispatch_queryset().order_by("-id")
        if (destination := visible_location(request, params.get("destination_id"))) is not None:
            qs = qs.filter(destination_location_id=destination)
        if "status" in params:
            qs = qs.filter(status=params["status"])
        page = self.paginate_queryset(qs)
        return self.get_paginated_response(self.get_serializer(page, many=True).data)

    @extend_schema(
        operation_id="dispatchesCreate",
        tags=["dispatches"],
        parameters=[IDEMPOTENCY],
        request=DispatchCreateSerializer,
        responses={201: DispatchSerializer, 400: ERROR, 401: ERROR, 403: ERROR, 409: ERROR},
    )
    def post(self, request: Request) -> Response:
        data = DispatchCreateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        operation_id = operation_id_for(request)

        def work() -> tuple[int, dict[str, Any]]:
            dispatch = services.create_dispatch(
                request._request, cast(User, request.user), data.validated_data, operation_id
            )
            return 201, dict(DispatchSerializer(services.dispatch_queryset().get(pk=dispatch.pk)).data)

        return idempotent(request, work)


class DispatchWaitingView(generics.GenericAPIView[Dispatch]):
    filter_backends = ()
    serializer_class = DispatchSerializer
    permission_classes = action_permissions("dispatches.waiting")

    @extend_schema(
        operation_id="dispatchesWaiting",
        tags=["dispatches"],
        parameters=[WaitingQuerySerializer],
        responses={200: DispatchSerializer(many=True), 400: ERROR, 401: ERROR, 403: ERROR},
    )
    def get(self, request: Request) -> Response:
        query = WaitingQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        branch_id = query.validated_data.get("branch_id")
        if active_role(cast(User, request.user)) == c.SUPER_ADMIN:
            if branch_id is None:
                raise ApiError(400, "validation_error", "Choose a branch.", "branch_id")
            if not Location.objects.filter(pk=branch_id, kind=LocationKind.BRANCH).exists():
                raise ApiError(400, "validation_error", "This branch does not exist.", "branch_id")
            branch = branch_id
        else:
            branch = cast(int, visible_location(request, branch_id))  # own branch; another one is 403
        qs = (
            services.dispatch_queryset()
            .filter(destination_location_id=branch, status=DispatchStatus.IN_TRANSIT)
            .order_by("id")
        )
        page = self.paginate_queryset(qs)
        return self.get_paginated_response(self.get_serializer(page, many=True).data)


class DispatchDetailView(APIView):
    permission_classes = action_permissions("dispatches.view")

    @extend_schema(
        operation_id="dispatchesRead",
        tags=["dispatches"],
        parameters=[ID_PARAM],
        responses={200: DispatchSerializer, 401: ERROR, 403: ERROR, 404: ERROR},
    )
    def get(self, request: Request, id: int) -> Response:
        dispatch = services.dispatch_queryset().filter(pk=id).first()
        if dispatch is None:
            raise ApiError(404, "not_found", "Not found.")
        own = visible_location(request, None)  # None for SA and WA; BA and FS: own branch only
        if own is not None and own != dispatch.destination_location_id:
            raise ApiError(404, "not_found", "Not found.")  # same as a missing id: no leak (OQ-30)
        return Response(DispatchSerializer(dispatch).data)


class DispatchReceiveView(APIView):
    permission_classes = action_permissions("dispatches.receive")

    @extend_schema(
        operation_id="dispatchesReceive",
        tags=["dispatches"],
        parameters=[ID_PARAM, IDEMPOTENCY],
        request=DispatchReceiveSerializer,
        responses={200: DispatchSerializer, 400: ERROR, 401: ERROR, 403: ERROR, 404: ERROR, 409: ERROR},
    )
    def post(self, request: Request, id: int) -> Response:
        data = DispatchReceiveSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        operation_id = operation_id_for(request)

        def work() -> tuple[int, dict[str, Any]]:
            dispatch = services.receive_dispatch(
                request._request, cast(User, request.user), id, data.validated_data, operation_id
            )
            return 200, dict(DispatchSerializer(services.dispatch_queryset().get(pk=dispatch.pk)).data)

        return idempotent(request, work)

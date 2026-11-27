"""Thin views for /api/v1/branches/* (contract B1.3, TASKS B3.2): validate, call the service, serialise."""

from typing import Any, cast

from django.shortcuts import get_object_or_404
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import generics, serializers
from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import User
from accounts.permissions import IsActiveAccount, PasswordChangeNotRequired
from accounts.serializers import BranchSerializer, ErrorSerializer
from branches import services
from branches.models import Location, LocationKind
from config.idempotency import idempotent
from roles.permissions import action_permissions

ERROR = OpenApiResponse(ErrorSerializer)
IDEMPOTENCY = OpenApiParameter("Idempotency-Key", OpenApiTypes.UUID, OpenApiParameter.HEADER, required=True)
READ_ERRORS = {401: ERROR}
WRITE_ERRORS = {400: ERROR, 401: ERROR, 403: ERROR, 404: ERROR, 409: ERROR}
CREATE_ERRORS = {400: ERROR, 401: ERROR, 403: ERROR, 409: ERROR}


class BranchWriteSerializer(serializers.Serializer[object]):
    code = serializers.CharField(max_length=20, required=False)
    name = serializers.CharField(max_length=100, required=False)
    branch_type = serializers.ChoiceField(choices=LocationKind.choices, required=False)


class BranchCreateSerializer(BranchWriteSerializer):
    branch_type = serializers.ChoiceField(choices=LocationKind.choices)  # required on create (MW.1)


class BranchQuerySerializer(serializers.Serializer[object]):
    kind = serializers.ChoiceField(choices=LocationKind.choices, required=False)
    branch_type = serializers.ChoiceField(choices=LocationKind.choices, required=False)  # alias of `kind`
    is_active = serializers.BooleanField(required=False, allow_null=True, default=None)  # None: no filter
    branch = serializers.IntegerField(required=False, min_value=1)


def _manage() -> list[BasePermission]:
    return [p() for p in action_permissions("branches.manage")]


class BranchListCreateView(generics.GenericAPIView[Location]):
    filter_backends = ()

    def get_permissions(self) -> list[BasePermission]:
        # Reading is open to every logged-in user (row 12); creating is Super Admin only (row 11).
        if self.request.method == "GET":
            return [IsActiveAccount(), PasswordChangeNotRequired()]
        return _manage()

    @extend_schema(
        operation_id="branchesList",
        tags=["branches"],
        parameters=[BranchQuerySerializer],
        responses={200: BranchSerializer(many=True), **READ_ERRORS},
    )
    def get(self, request: Request) -> Response:
        query = BranchQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        qs = services.visible_locations(cast(User, request.user), query.validated_data.get("is_active"))
        only = services.branch_filter(cast(User, request.user), query.validated_data.get("branch"))
        if only is not None:
            qs = qs.filter(pk=only)
        if "kind" in query.validated_data:
            qs = qs.filter(kind=query.validated_data["kind"])
        if "branch_type" in query.validated_data:
            qs = qs.filter(kind=query.validated_data["branch_type"])
        page = self.paginate_queryset(qs.order_by("id"))
        return self.get_paginated_response(BranchSerializer(page, many=True).data)

    @extend_schema(
        operation_id="branchesCreate",
        tags=["branches"],
        parameters=[IDEMPOTENCY],
        request=BranchCreateSerializer,
        responses={201: BranchSerializer, **CREATE_ERRORS},
    )
    def post(self, request: Request) -> Response:
        data = BranchCreateSerializer(data=request.data)
        data.is_valid(raise_exception=True)

        def work() -> tuple[int, dict[str, Any]]:
            branch = services.create_branch(request._request, cast(User, request.user), data.validated_data)
            return 201, dict(BranchSerializer(branch).data)

        return idempotent(request, work)


class BranchDetailView(APIView):
    def get_permissions(self) -> list[BasePermission]:
        if self.request.method == "GET":
            return [IsActiveAccount(), PasswordChangeNotRequired()]
        return _manage()

    @extend_schema(
        operation_id="branchesRead",
        tags=["branches"],
        responses={200: BranchSerializer, 401: ERROR, 404: ERROR},
    )
    def get(self, request: Request, id: int) -> Response:
        branch = get_object_or_404(services.visible_locations(cast(User, request.user)), pk=id)
        return Response(BranchSerializer(branch).data)

    @extend_schema(
        operation_id="branchesUpdate",
        tags=["branches"],
        parameters=[IDEMPOTENCY],
        request=BranchWriteSerializer,
        responses={200: BranchSerializer, **WRITE_ERRORS},
    )
    def patch(self, request: Request, id: int) -> Response:
        data = BranchWriteSerializer(data=request.data, partial=True)
        data.is_valid(raise_exception=True)

        def work() -> tuple[int, dict[str, Any]]:
            branch = services.update_branch(
                request._request, cast(User, request.user), id, data.validated_data
            )
            return 200, dict(BranchSerializer(branch).data)

        return idempotent(request, work)


class _BranchActiveView(APIView):
    active = False

    def get_permissions(self) -> list[BasePermission]:
        return _manage()

    def post(self, request: Request, id: int) -> Response:
        def work() -> tuple[int, dict[str, Any]]:
            branch = services.set_branch_active(request._request, cast(User, request.user), id, self.active)
            return 200, dict(BranchSerializer(branch).data)

        return idempotent(request, work)


class BranchDeactivateView(_BranchActiveView):
    active = False

    @extend_schema(
        operation_id="branchesDeactivate",
        tags=["branches"],
        parameters=[IDEMPOTENCY],
        request=None,
        responses={200: BranchSerializer, **WRITE_ERRORS},
    )
    def post(self, request: Request, id: int) -> Response:
        return super().post(request, id)


class BranchActivateView(_BranchActiveView):
    active = True

    @extend_schema(
        operation_id="branchesActivate",
        tags=["branches"],
        parameters=[IDEMPOTENCY],
        request=None,
        responses={200: BranchSerializer, **WRITE_ERRORS},
    )
    def post(self, request: Request, id: int) -> Response:
        return super().post(request, id)

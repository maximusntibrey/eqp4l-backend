"""Thin views for /api/v1/working-branch/ (contract B1.3, TASKS B3.1)."""

from typing import Any, cast

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import serializers
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.me import build_me, working_branch
from accounts.models import User
from accounts.serializers import BranchSerializer, ErrorSerializer, MeSerializer
from branch_access import services
from config.idempotency import idempotent
from roles.permissions import action_permissions

ERROR = OpenApiResponse(ErrorSerializer)


class WorkingBranchSerializer(serializers.Serializer[object]):
    working_branch = BranchSerializer(allow_null=True)


class WorkingBranchSetSerializer(serializers.Serializer[object]):
    branch_id = serializers.IntegerField()


class WorkingBranchView(APIView):
    permission_classes = action_permissions("working_branch.select")  # row 10: FS and SA only

    @extend_schema(
        operation_id="workingBranchGet",
        tags=["working-branch"],
        responses={200: WorkingBranchSerializer, 401: ERROR, 403: ERROR},
    )
    def get(self, request: Request) -> Response:
        branch = working_branch(cast(User, request.user), request._request)
        return Response(WorkingBranchSerializer({"working_branch": branch}).data)

    @extend_schema(
        operation_id="workingBranchSet",
        tags=["working-branch"],
        parameters=[
            OpenApiParameter("Idempotency-Key", OpenApiTypes.UUID, OpenApiParameter.HEADER, required=True)
        ],
        request=WorkingBranchSetSerializer,
        responses={200: MeSerializer, 400: ERROR, 401: ERROR, 403: ERROR, 409: ERROR},
    )
    def put(self, request: Request) -> Response:
        data = WorkingBranchSetSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        user = cast(User, request.user)

        def work() -> tuple[int, dict[str, Any]]:
            services.set_working_branch(request._request, user, data.validated_data["branch_id"])
            return 200, dict(MeSerializer(build_me(request._request, user)).data)

        return idempotent(request, work)

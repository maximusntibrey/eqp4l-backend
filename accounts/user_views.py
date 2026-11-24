"""Thin views for /api/v1/users/* (contract B1.3, TASKS B3.3): validate, call the service, serialise."""

from typing import Any, cast

from django.shortcuts import get_object_or_404
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import generics, serializers
from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts import user_admin as admin
from accounts.me import user_payload
from accounts.models import User, UserStatus
from accounts.serializers import ROLE_CHOICES, ErrorSerializer, UserSerializer
from branches.services import branch_filter
from config.idempotency import derive_one_time_password, idempotent
from roles import constants as c
from roles.permissions import action_permissions

ERROR = OpenApiResponse(ErrorSerializer)
IDEMPOTENCY = OpenApiParameter("Idempotency-Key", OpenApiTypes.UUID, OpenApiParameter.HEADER, required=True)
READ_ERRORS = {401: ERROR, 403: ERROR, 404: ERROR}
WRITE_ERRORS = {400: ERROR, 401: ERROR, 403: ERROR, 404: ERROR, 409: ERROR}
CREATE_ERRORS = {400: ERROR, 401: ERROR, 403: ERROR, 409: ERROR}
PERMISSION_CHOICES = [(p, p) for p in c.PERSON_PERMISSIONS]
STATUS_TARGETS = [UserStatus.ACTIVE.value, UserStatus.SUSPENDED.value, UserStatus.DEACTIVATED.value]


class UserCreateSerializer(serializers.Serializer[object]):
    full_name = serializers.CharField(max_length=150)
    roles = serializers.ListField(child=serializers.ChoiceField(choices=ROLE_CHOICES), min_length=1)
    permanent_location_id = serializers.IntegerField(required=False)


class UserUpdateSerializer(serializers.Serializer[object]):
    full_name = serializers.CharField(max_length=150, required=False)
    roles = serializers.ListField(
        child=serializers.ChoiceField(choices=ROLE_CHOICES), min_length=1, required=False
    )
    permanent_location_id = serializers.IntegerField(required=False, allow_null=True)


class UserWithOneTimePasswordSerializer(UserSerializer):
    one_time_password = serializers.CharField()
    one_time_password_expires_at = serializers.DateTimeField()


class ResetPasswordResponseSerializer(serializers.Serializer[object]):
    one_time_password = serializers.CharField()
    one_time_password_expires_at = serializers.DateTimeField()


class UserStatusRequestSerializer(serializers.Serializer[object]):
    status = serializers.ChoiceField(choices=STATUS_TARGETS)
    reason = serializers.CharField(max_length=500, required=False, allow_blank=True)


class UserPermissionsSerializer(serializers.Serializer[object]):
    permissions = serializers.ListField(child=serializers.ChoiceField(choices=PERMISSION_CHOICES))


class UserQuerySerializer(serializers.Serializer[object]):
    status = serializers.ChoiceField(choices=UserStatus.choices, required=False)
    role = serializers.ChoiceField(choices=ROLE_CHOICES, required=False)
    q = serializers.CharField(required=False, allow_blank=True)
    branch = serializers.IntegerField(required=False, min_value=1)


def _manage() -> list[BasePermission]:
    return [p() for p in action_permissions("users.manage")]


def _view() -> list[BasePermission]:
    return [p() for p in action_permissions("users.view")]


def _payload(user: User) -> dict[str, Any]:
    return dict(UserSerializer(user_payload(user)).data)


def _expiry_iso(user: User) -> str:
    return serializers.DateTimeField().to_representation(admin.one_time_password_expiry(user))


class UserListCreateView(generics.GenericAPIView[User]):
    filter_backends = ()

    def get_permissions(self) -> list[BasePermission]:
        return _view() if self.request.method == "GET" else _manage()

    @extend_schema(
        operation_id="usersList",
        tags=["users"],
        parameters=[UserQuerySerializer],
        responses={200: UserSerializer(many=True), 401: ERROR, 403: ERROR},
    )
    def get(self, request: Request) -> Response:
        query = UserQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        params = dict(query.validated_data)
        params["branch"] = branch_filter(cast(User, request.user), params.get("branch"))
        qs = admin.filter_users(admin.visible_users(cast(User, request.user)), params)
        page = self.paginate_queryset(qs)
        return self.get_paginated_response([_payload(u) for u in page or []])

    @extend_schema(
        operation_id="usersCreate",
        tags=["users"],
        parameters=[IDEMPOTENCY],
        request=UserCreateSerializer,
        responses={201: UserWithOneTimePasswordSerializer, **CREATE_ERRORS},
    )
    def post(self, request: Request) -> Response:
        data = UserCreateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        otp = derive_one_time_password(request)

        def work() -> tuple[int, dict[str, Any]]:
            user = admin.create_managed_user(
                request._request, cast(User, request.user), data.validated_data, otp
            )
            return 201, {**_payload(user), "one_time_password_expires_at": _expiry_iso(user)}

        # The password is never stored with the replay record; it is derived again from the key.
        return idempotent(request, work, secrets=lambda: {"one_time_password": otp})


class UserDetailView(APIView):
    def get_permissions(self) -> list[BasePermission]:
        return _view() if self.request.method == "GET" else _manage()

    @extend_schema(operation_id="usersRead", tags=["users"], responses={200: UserSerializer, **READ_ERRORS})
    def get(self, request: Request, id: int) -> Response:
        user = get_object_or_404(admin.visible_users(cast(User, request.user)), pk=id)
        return Response(_payload(user))

    @extend_schema(
        operation_id="usersUpdate",
        tags=["users"],
        parameters=[IDEMPOTENCY],
        request=UserUpdateSerializer,
        responses={200: UserSerializer, **WRITE_ERRORS},
    )
    def patch(self, request: Request, id: int) -> Response:
        data = UserUpdateSerializer(data=request.data, partial=True)
        data.is_valid(raise_exception=True)
        # login_id is not a serializer field, so look at the raw body: the contract says 400 on attempt
        payload = {**data.validated_data, **({"login_id": 1} if "login_id" in request.data else {})}

        def work() -> tuple[int, dict[str, Any]]:
            user = admin.update_managed_user(request._request, cast(User, request.user), id, payload)
            return 200, _payload(user)

        return idempotent(request, work)


class UserResetPasswordView(APIView):
    permission_classes = action_permissions("users.manage")

    @extend_schema(
        operation_id="usersResetPassword",
        tags=["users"],
        parameters=[IDEMPOTENCY],
        request=None,
        responses={200: ResetPasswordResponseSerializer, **WRITE_ERRORS},
    )
    def post(self, request: Request, id: int) -> Response:
        otp = derive_one_time_password(request)

        def work() -> tuple[int, dict[str, Any]]:
            expires = admin.reset_user_password(request._request, cast(User, request.user), id, otp)
            return 200, {
                "one_time_password_expires_at": serializers.DateTimeField().to_representation(expires)
            }

        return idempotent(request, work, secrets=lambda: {"one_time_password": otp})


class UserStatusView(APIView):
    permission_classes = action_permissions("users.manage")

    @extend_schema(
        operation_id="usersSetStatus",
        tags=["users"],
        parameters=[IDEMPOTENCY],
        request=UserStatusRequestSerializer,
        responses={200: UserSerializer, **WRITE_ERRORS},
    )
    def post(self, request: Request, id: int) -> Response:
        data = UserStatusRequestSerializer(data=request.data)
        data.is_valid(raise_exception=True)

        def work() -> tuple[int, dict[str, Any]]:
            user = admin.set_user_status(
                request._request,
                cast(User, request.user),
                id,
                data.validated_data["status"],
                data.validated_data.get("reason", ""),
            )
            return 200, _payload(user)

        return idempotent(request, work)


class UserPermissionsView(APIView):
    permission_classes = action_permissions("users.manage")  # row 8: Super Admin only

    @extend_schema(
        operation_id="usersPermissionsRead",
        tags=["users"],
        responses={200: UserPermissionsSerializer, **READ_ERRORS},
    )
    def get(self, request: Request, id: int) -> Response:
        user = get_object_or_404(User, pk=id)
        return Response({"permissions": user_payload(user)["permissions"]})

    @extend_schema(
        operation_id="usersPermissionsSet",
        tags=["users"],
        parameters=[IDEMPOTENCY],
        request=UserPermissionsSerializer,
        responses={200: UserPermissionsSerializer, **WRITE_ERRORS},
    )
    def put(self, request: Request, id: int) -> Response:
        data = UserPermissionsSerializer(data=request.data)
        data.is_valid(raise_exception=True)

        def work() -> tuple[int, dict[str, Any]]:
            held = admin.set_person_permissions(
                request._request, cast(User, request.user), id, data.validated_data["permissions"]
            )
            return 200, {"permissions": held}

        return idempotent(request, work)

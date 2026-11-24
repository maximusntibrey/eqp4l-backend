"""Thin views for /api/v1/auth/*: validate, call the service, return a serializer (contract B1.3)."""

from typing import Any, cast

from django.middleware.csrf import get_token
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts import services
from accounts.me import build_me
from accounts.models import User
from accounts.permissions import IsActiveAccount
from accounts.serializers import (
    CsrfSerializer,
    ErrorSerializer,
    LoginRequestSerializer,
    MeSerializer,
    PasswordChangeRequestSerializer,
)

ERROR = OpenApiResponse(ErrorSerializer)


class CsrfView(APIView):
    """Sets the CSRF cookie and returns the token for the X-CSRFToken header."""

    authentication_classes: list[Any] = []
    permission_classes = [AllowAny]

    @extend_schema(operation_id="authCsrf", tags=["auth"], responses={200: CsrfSerializer}, auth=[])
    def get(self, request: Request) -> Response:
        return Response({"csrf_token": get_token(request)})


@method_decorator(csrf_protect, name="dispatch")  # login has no session yet, so DRF would skip the CSRF check
class LoginView(APIView):
    authentication_classes: list[Any] = []
    permission_classes = [AllowAny]

    @extend_schema(
        operation_id="authLogin",
        tags=["auth"],
        request=LoginRequestSerializer,
        responses={200: MeSerializer, 400: ERROR, 401: ERROR, 403: ERROR, 429: ERROR},
    )
    def post(self, request: Request) -> Response:
        data = LoginRequestSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        user = services.authenticate_login(
            request._request, data.validated_data["login_id"], data.validated_data["password"]
        )
        services.complete_login(request._request, user)
        return Response(MeSerializer(build_me(request._request, user)).data)


class LogoutView(APIView):
    permission_classes = [IsActiveAccount]  # open even while a password change is pending

    @extend_schema(operation_id="authLogout", tags=["auth"], request=None, responses={204: None, 401: ERROR})
    def post(self, request: Request) -> Response:
        services.end_session(request._request, cast(User, request.user))
        return Response(status=status.HTTP_204_NO_CONTENT)


class MeView(APIView):
    permission_classes = [IsActiveAccount]

    @extend_schema(operation_id="authMe", tags=["auth"], responses={200: MeSerializer, 401: ERROR})
    def get(self, request: Request) -> Response:
        return Response(MeSerializer(build_me(request._request, cast(User, request.user))).data)


class PasswordView(APIView):
    permission_classes = [IsActiveAccount]

    @extend_schema(
        operation_id="authChangePassword",
        tags=["auth"],
        request=PasswordChangeRequestSerializer,
        responses={204: None, 400: ERROR, 401: ERROR},
    )
    def post(self, request: Request) -> Response:
        data = PasswordChangeRequestSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        services.change_password(
            request._request,
            cast(User, request.user),
            data.validated_data["current_password"],
            data.validated_data["new_password"],
        )
        return Response(status=status.HTTP_204_NO_CONTENT)

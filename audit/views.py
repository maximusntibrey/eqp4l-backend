"""Activity log API (B7.2): GET /activity-log/ (table rows 41, 45). Read-only, no cost."""

from datetime import date, datetime, time, timedelta
from typing import Any, cast
from zoneinfo import ZoneInfo

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import generics, serializers
from rest_framework.request import Request
from rest_framework.response import Response

from accounts.models import User
from accounts.serializers import ErrorSerializer
from audit.models import AuditEvent
from audit.queries import scoped_events
from roles.permissions import action_permissions

ERROR = OpenApiResponse(ErrorSerializer)
ACCRA = ZoneInfo("Africa/Accra")


class ActivityEventSerializer(serializers.ModelSerializer[AuditEvent]):
    user_id = serializers.IntegerField(source="actor_id", allow_null=True)
    user_login_id = serializers.CharField(source="actor_login_id")
    user_role = serializers.CharField(source="actor_role")
    branch_id = serializers.IntegerField(source="location_id", allow_null=True)
    branch_name = serializers.SerializerMethodField()

    class Meta:
        model = AuditEvent
        fields = [
            "id",
            "occurred_at",
            "user_id",
            "user_login_id",
            "user_role",
            "branch_id",
            "branch_name",
            "action",
            "target_type",
            "target_ref",
            "is_self_approval",
        ]

    def get_branch_name(self, obj: AuditEvent) -> str | None:
        return obj.location.name if obj.location else None


class ActivityQuerySerializer(serializers.Serializer[object]):
    user_id = serializers.IntegerField(required=False, min_value=1)
    branch_id = serializers.IntegerField(required=False, min_value=1)
    action = serializers.CharField(required=False, max_length=60)
    date_from = serializers.DateField(required=False)
    date_to = serializers.DateField(required=False)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if "date_from" in attrs and "date_to" in attrs and attrs["date_from"] > attrs["date_to"]:
            raise serializers.ValidationError({"date_to": "The end date is before the start date."})
        return attrs


def _day_start(day: date) -> datetime:
    return datetime.combine(day, time.min, tzinfo=ACCRA)


class ActivityLogView(generics.GenericAPIView[AuditEvent]):
    filter_backends = ()
    permission_classes = action_permissions("activity.view")
    serializer_class = ActivityEventSerializer

    @extend_schema(
        operation_id="activityLogList",
        tags=["activity"],
        parameters=[ActivityQuerySerializer],
        responses={200: ActivityEventSerializer(many=True), 400: ERROR, 401: ERROR, 403: ERROR},
    )
    def get(self, request: Request) -> Response:
        query = ActivityQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        params = query.validated_data
        qs = scoped_events(cast(User, request.user), request._request.session, params.get("branch_id"))
        if "user_id" in params:
            qs = qs.filter(actor_id=params["user_id"])
        if "action" in params:
            qs = qs.filter(action=params["action"])
        if "date_from" in params:
            qs = qs.filter(occurred_at__gte=_day_start(params["date_from"]))
        if "date_to" in params:  # the whole last day, Accra time
            qs = qs.filter(occurred_at__lt=_day_start(params["date_to"] + timedelta(days=1)))
        page = self.paginate_queryset(qs)
        return self.get_paginated_response(self.get_serializer(page, many=True).data)

"""Activity log API (B7.2): GET /activity-log/ (table rows 41, 45). Read-only, no cost."""

import csv
from datetime import date, datetime, time, timedelta
from typing import Any, cast
from zoneinfo import ZoneInfo

from django.db.models import Q, QuerySet
from django.http import HttpResponse
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import generics, serializers
from rest_framework.negotiation import BaseContentNegotiation
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import User
from accounts.serializers import ErrorSerializer
from audit.models import AuditEvent
from audit.queries import scoped_events
from roles.permissions import action_permissions

ERROR = OpenApiResponse(ErrorSerializer)
ACCRA = ZoneInfo("Africa/Accra")
EXPORT_ROW_CAP = 5000
# `?ordering=` values (leading "-" = descending) mapped to columns; the id keeps the order stable.
ORDERING = {"timestamp": "occurred_at", "user": "actor_login_id", "action": "action"}
ORDERING_CHOICES = [name for key in ORDERING for name in (key, f"-{key}")]
FORMULA_STARTS = ("=", "+", "-", "@", "\t", "\r")
CSV_COLUMNS = [
    "occurred_at", "user_login_id", "user_role", "branch_name", "action", "target_type", "target_ref",
    "is_self_approval",
]  # fmt: skip


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
    target_type = serializers.CharField(required=False, max_length=40)  # the module / entity type
    search = serializers.CharField(required=False, max_length=100)
    ordering = serializers.ChoiceField(choices=ORDERING_CHOICES, required=False)
    date_from = serializers.DateField(required=False)
    date_to = serializers.DateField(required=False)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if "date_from" in attrs and "date_to" in attrs and attrs["date_from"] > attrs["date_to"]:
            raise serializers.ValidationError({"date_to": "The end date is before the start date."})
        return attrs


def _day_start(day: date) -> datetime:
    return datetime.combine(day, time.min, tzinfo=ACCRA)


def filtered_events(request: Request) -> QuerySet[AuditEvent]:
    """The caller's scoped events with every filter and the ordering applied (shared by list and export).

    Search is a case-insensitive match on metadata only (action, target type and ref, user login id); the
    stored before/after values are never searched, so cost can not leak through it.
    """
    query = ActivityQuerySerializer(data=request.query_params)
    query.is_valid(raise_exception=True)
    params = query.validated_data
    qs = scoped_events(cast(User, request.user), request._request.session, params.get("branch_id"))
    if "user_id" in params:
        qs = qs.filter(actor_id=params["user_id"])
    if "action" in params:
        qs = qs.filter(action=params["action"])
    if "target_type" in params:
        qs = qs.filter(target_type=params["target_type"])
    if "search" in params:
        term = params["search"].strip()
        qs = qs.filter(
            Q(action__icontains=term)
            | Q(target_type__icontains=term)
            | Q(target_ref__icontains=term)
            | Q(actor_login_id__icontains=term)
        )
    if "date_from" in params:
        qs = qs.filter(occurred_at__gte=_day_start(params["date_from"]))
    if "date_to" in params:  # the whole last day, Accra time
        qs = qs.filter(occurred_at__lt=_day_start(params["date_to"] + timedelta(days=1)))
    if "ordering" in params:
        name = params["ordering"]
        column = ORDERING[name.lstrip("-")]
        sign = "-" if name.startswith("-") else ""
        qs = qs.order_by(f"{sign}{column}", f"{sign}id")
    return qs  # default: newest first (scoped_events)


QUERY_PARAMS = [ActivityQuerySerializer]


class ActivityLogView(generics.GenericAPIView[AuditEvent]):
    filter_backends = ()
    permission_classes = action_permissions("activity.view")
    serializer_class = ActivityEventSerializer

    @extend_schema(
        operation_id="activityLogList",
        tags=["activity"],
        parameters=QUERY_PARAMS,
        responses={200: ActivityEventSerializer(many=True), 400: ERROR, 401: ERROR, 403: ERROR},
    )
    def get(self, request: Request) -> Response:
        page = self.paginate_queryset(filtered_events(request))
        return self.get_paginated_response(self.get_serializer(page, many=True).data)


def _safe_cell(value: object) -> str:
    """Stop spreadsheet formula injection: a leading = + - @ tab or CR is prefixed with an apostrophe."""
    text = "" if value is None else str(value)
    return f"'{text}" if text[:1] in FORMULA_STARTS else text


class AcceptAnything(BaseContentNegotiation):
    """The export streams CSV from a plain HttpResponse; browsers and clients may ask for text/csv."""

    def select_parser(self, request: Request, parsers: Any) -> Any:
        return parsers[0] if parsers else None

    def select_renderer(self, request: Request, renderers: Any, format_suffix: Any = None) -> Any:
        return renderers[0], renderers[0].media_type


class ActivityLogExportView(APIView):
    content_negotiation_class = AcceptAnything
    permission_classes = action_permissions("activity.view")

    @extend_schema(
        operation_id="activityLogExport",
        tags=["activity"],
        parameters=QUERY_PARAMS,
        responses={
            200: OpenApiResponse(OpenApiTypes.STR, description="CSV file (text/csv), at most 5000 rows."),
            400: ERROR,
            401: ERROR,
            403: ERROR,
        },
    )
    def get(self, request: Request) -> HttpResponse:
        qs = filtered_events(request)[: EXPORT_ROW_CAP + 1]
        rows = ActivityEventSerializer(qs, many=True).data
        truncated = len(rows) > EXPORT_ROW_CAP
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = 'attachment; filename="activity-log.csv"'
        response["X-Export-Truncated"] = "true" if truncated else "false"
        writer = csv.writer(response)
        writer.writerow(CSV_COLUMNS)
        for row in rows[:EXPORT_ROW_CAP]:
            moment = datetime.fromisoformat(str(row["occurred_at"])).astimezone(ACCRA)
            when = moment.isoformat(timespec="seconds")
            writer.writerow([when] + [_safe_cell(row[c]) for c in CSV_COLUMNS[1:]])
        return response

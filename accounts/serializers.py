"""Request and response shapes for /auth/* (contract schemas Error, Branch, User, Me)."""

from rest_framework import serializers

from accounts.models import UserStatus
from branches.models import LocationKind
from roles import constants as c
from roles.permissions import ACTIONS

ROLE_CHOICES = [(code, code) for code in c.ROLE_PRIORITY]


class ErrorItemSerializer(serializers.Serializer[object]):
    field = serializers.CharField(allow_null=True)
    message = serializers.CharField()


class ErrorSerializer(serializers.Serializer[object]):
    code = serializers.CharField()
    message = serializers.CharField()
    errors = ErrorItemSerializer(many=True)  # type: ignore[assignment]


class LoginRequestSerializer(serializers.Serializer[object]):
    login_id = serializers.CharField(max_length=64)
    password = serializers.CharField(max_length=256, trim_whitespace=False, write_only=True)


class PasswordChangeRequestSerializer(serializers.Serializer[object]):
    current_password = serializers.CharField(max_length=256, trim_whitespace=False, write_only=True)
    new_password = serializers.CharField(
        min_length=10, max_length=256, trim_whitespace=False, write_only=True
    )


class BranchSerializer(serializers.Serializer[object]):
    id = serializers.IntegerField()
    kind = serializers.ChoiceField(choices=LocationKind.choices)
    code = serializers.CharField()
    name = serializers.CharField()
    is_active = serializers.BooleanField()
    created_at = serializers.DateTimeField(required=False)
    updated_at = serializers.DateTimeField(required=False)


class UserSerializer(serializers.Serializer[object]):
    id = serializers.IntegerField()
    login_id = serializers.CharField()
    full_name = serializers.CharField()
    status = serializers.ChoiceField(choices=UserStatus.choices)
    roles = serializers.ListField(child=serializers.ChoiceField(choices=ROLE_CHOICES))
    permanent_location_id = serializers.IntegerField(allow_null=True)
    must_change_password = serializers.BooleanField()
    permissions = serializers.ListField(
        child=serializers.ChoiceField(choices=[(p, p) for p in c.PERSON_PERMISSIONS])
    )
    last_login_at = serializers.DateTimeField(allow_null=True, required=False)
    created_at = serializers.DateTimeField(required=False)


class MenuItemSerializer(serializers.Serializer[object]):
    key = serializers.CharField()
    label = serializers.CharField()  # type: ignore[assignment]
    path = serializers.CharField()


class MeSerializer(serializers.Serializer[object]):
    user = UserSerializer()
    active_role = serializers.ChoiceField(choices=ROLE_CHOICES)
    working_branch = BranchSerializer(allow_null=True)
    must_pick_branch = serializers.BooleanField()
    all_branches = serializers.BooleanField()
    can_assign_multiple_roles = serializers.BooleanField()
    must_change_password = serializers.BooleanField()
    permissions = serializers.ListField(child=serializers.ChoiceField(choices=[(a, a) for a in ACTIONS]))
    menu = MenuItemSerializer(many=True)
    home_links = MenuItemSerializer(many=True)


class CsrfSerializer(serializers.Serializer[object]):
    csrf_token = serializers.CharField()

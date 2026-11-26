from django.urls import path

from accounts import user_views as v

urlpatterns = [
    path("", v.UserListCreateView.as_view(), name="users"),
    path("<int:id>/", v.UserDetailView.as_view(), name="user"),
    path("<int:id>/reset-password/", v.UserResetPasswordView.as_view(), name="user-reset-password"),
    path("<int:id>/status/", v.UserStatusView.as_view(), name="user-status"),
    path("<int:id>/permissions/", v.UserPermissionsView.as_view(), name="user-permissions"),
]

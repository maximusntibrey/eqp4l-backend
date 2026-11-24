from django.urls import include, path

from config.health import health
from inventory.dashboard import DashboardView

urlpatterns = [
    path("health/", health, name="health"),
    path("api/v1/auth/", include("accounts.urls")),
    path("api/v1/working-branch/", include("branch_access.urls")),
    path("api/v1/branches/", include("branches.urls")),
    path("api/v1/users/", include("accounts.user_urls")),
    path("api/v1/dashboard/", DashboardView.as_view(), name="dashboard"),
]

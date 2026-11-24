from django.conf import settings
from django.conf.urls.static import static
from django.urls import include, path

from config.health import health
from inventory.dashboard import DashboardView

urlpatterns = [
    path("health/", health, name="health"),
    path("api/v1/auth/", include("accounts.urls")),
    path("api/v1/working-branch/", include("branch_access.urls")),
    path("api/v1/branches/", include("branches.urls")),
    path("api/v1/users/", include("accounts.user_urls")),
    path("api/v1/", include("inventory.urls")),
    path("api/v1/dashboard/", DashboardView.as_view(), name="dashboard"),
]

if settings.DEBUG:  # local dev only: the host serves uploaded images in production
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

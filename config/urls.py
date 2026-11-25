from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from django.views.static import serve

from config.health import health
from inventory.dashboard import DashboardView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("health/", health, name="health"),
    path("api/v1/auth/", include("accounts.urls")),
    path("api/v1/working-branch/", include("branch_access.urls")),
    path("api/v1/branches/", include("branches.urls")),
    path("api/v1/users/", include("accounts.user_urls")),
    path("api/v1/", include("inventory.urls")),
    path("api/v1/", include("warehouse.urls")),
    path("api/v1/", include("transfers.urls")),
    path("api/v1/", include("sales.urls")),
    path("api/v1/", include("audit.urls")),
    path("api/v1/dashboard/", DashboardView.as_view(), name="dashboard"),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
else:
    urlpatterns += [
        path("media/<path:path>", serve, {"document_root": settings.MEDIA_ROOT}),
    ]

from django.urls import include, path

from config.health import health

urlpatterns = [
    path("health/", health, name="health"),
    path("api/v1/auth/", include("accounts.urls")),
]

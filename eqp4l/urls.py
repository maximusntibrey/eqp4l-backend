"""Root URL configuration.

/health/ is the only route until the approved endpoint list (B1.3) adds endpoints under
/api/v1/.
"""

from django.urls import URLPattern, URLResolver, path

from eqp4l.health import health

urlpatterns: list[URLPattern | URLResolver] = [
    path("health/", health, name="health"),
]

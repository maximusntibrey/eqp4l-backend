"""Root URL configuration.

Empty on purpose (step B1.0, tooling only). Endpoints are added from the approved
endpoint list (B1.3) under /api/v1/, and /health/ in O1.7.
"""

from django.urls import URLPattern, URLResolver

urlpatterns: list[URLPattern | URLResolver] = []

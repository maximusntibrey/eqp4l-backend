"""Health check (step O1.7): GET /health/ for the external uptime monitor and the smoke tests.

Checks the app (it answered) and the database (a trivial query). The body is a plain word:
no versions, settings, hostnames or error text are ever returned. Unauthenticated on
purpose, because the uptime monitor has no session (DevOps s3 and s8 do not ask for login).
"""

import logging

from django.db import DatabaseError, OperationalError, connection
from django.http import HttpRequest, HttpResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_safe

logger = logging.getLogger(__name__)


@never_cache
@require_safe
def health(request: HttpRequest) -> HttpResponse:
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except (DatabaseError, OperationalError) as exc:
        # Log only the exception class: the message can contain the host or user name.
        logger.error("Health check: database unavailable (%s)", type(exc).__name__)
        return HttpResponse("unavailable", status=503, content_type="text/plain")
    return HttpResponse("ok", content_type="text/plain")

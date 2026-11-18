"""ASGI entry point (not used for deployment yet; Gunicorn serves WSGI)."""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "eqp4l.settings")

application = get_asgi_application()

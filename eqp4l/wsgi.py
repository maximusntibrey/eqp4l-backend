"""WSGI entry point, served by Gunicorn (T.13): ``gunicorn eqp4l.wsgi``."""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "eqp4l.settings")

application = get_wsgi_application()

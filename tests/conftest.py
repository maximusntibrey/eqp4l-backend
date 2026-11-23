import os

# Settings read env at import; make sure tests never depend on a developer's .env.
os.environ.setdefault("DJANGO_DEBUG", "True")
os.environ.setdefault("DJANGO_SECRET_KEY", "test-only-secret-key")

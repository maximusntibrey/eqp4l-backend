"""Django settings for the eqp4l-backend project (Payless4Laptops Inventory & Warehouse).

Every secret and every environment-specific value comes from environment variables,
read with django-environ (TASKS 0.3, 0.6). Locally they come from a git-ignored ``.env``
file (copy ``.env.example``); on staging and production they come from the host's secret
store. There are no secret defaults in this file.

Scope (step B1.0, tooling only): no project apps, no models and no migrations yet.
"""

from pathlib import Path

import environ
import sentry_sdk

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env()
_env_file = BASE_DIR / ".env"
if _env_file.is_file():
    env.read_env(str(_env_file))

# --- Core -------------------------------------------------------------------------------

# Required: no default, so a missing key fails loudly instead of using a known value.
SECRET_KEY: str = env("DJANGO_SECRET_KEY")
DEBUG: bool = env.bool("DJANGO_DEBUG", default=False)
ALLOWED_HOSTS: list[str] = env.list("DJANGO_ALLOWED_HOSTS", default=[])

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.staticfiles",
    "corsheaders",
    "django_filters",
    "rest_framework",
    "drf_spectacular",
    # Project apps (accounts, roles, branches, inventory, ...) are added from B2.1,
    # after the owner approves the B1.2 ERD (SKILLS.md Database Standards).
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "eqp4l.urls"
WSGI_APPLICATION = "eqp4l.wsgi.application"
ASGI_APPLICATION = "eqp4l.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
            ],
        },
    },
]

# --- Database (PostgreSQL only, TASKS T.8) ----------------------------------------------

# Required, for example postgres://user:password@localhost:5432/eqp4l (see .env.example).
DATABASES = {"default": env.db("DATABASE_URL")}

# --- Users and passwords ----------------------------------------------------------------

# AUTH_USER_MODEL is deliberately NOT set yet. The custom user model (login IDs SA-0001 /
# USR-0001) is created in B2.2 from the first project migration, only after the owner
# approves the B1.2 ERD (TASKS B1.2, SKILLS.md Coding and Database Standards).
# Do not run `migrate` against a shared database before then.

# T.9: Argon2 first (SKILLS.md Security Standards); PBKDF2 kept only to verify old hashes.
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
]
# Password rules (AUTH_PASSWORD_VALIDATORS) are set in B2.3 from the approved policy.

# --- Sessions, cookies, CORS and CSRF ---------------------------------------------------

# Secure by default; only local .env files switch these off (staging and production are
# HTTPS only, DevOps s3).
SESSION_COOKIE_SECURE: bool = env.bool("SESSION_COOKIE_SECURE", default=True)
CSRF_COOKIE_SECURE: bool = env.bool("CSRF_COOKIE_SECURE", default=True)
SESSION_COOKIE_HTTPONLY = True

# Only the frontend's own origins (DevOps s3). Credentials are allowed because the API
# uses session-cookie login (SKILLS.md API Development Standards).
CORS_ALLOWED_ORIGINS: list[str] = env.list("CORS_ALLOWED_ORIGINS", default=[])
CORS_ALLOW_CREDENTIALS = True
CSRF_TRUSTED_ORIGINS: list[str] = env.list("CSRF_TRUSTED_ORIGINS", default=[])

# --- Internationalisation ---------------------------------------------------------------

LANGUAGE_CODE = "en-us"
# Timestamps are timezone-aware (USE_TZ stores UTC) and shown in Africa/Accra.
TIME_ZONE: str = env("TIME_ZONE", default="Africa/Accra")
USE_I18N = True
USE_TZ = True

# --- Static files (WhiteNoise, T.13) ----------------------------------------------------

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

# --- Django REST Framework and the OpenAPI contract (T.6, T.7) --------------------------

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
    ],
    # Deny by default: every endpoint must declare the permission it needs.
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_FILTER_BACKENDS": [
        "django_filters.rest_framework.DjangoFilterBackend",
    ],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    # Pagination, the error format and login throttling rates are set in B1.3 / B2.3.
}

SPECTACULAR_SETTINGS = {
    "TITLE": "Payless4Laptops Inventory & Warehouse API",
    # The contract version is set when the contract is published (B1.3).
    "VERSION": "0.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
}

# --- Error monitoring (Sentry, T.13) ----------------------------------------------------

# Off unless SENTRY_DSN is set in the environment. The DSN never goes in git.
SENTRY_DSN: str = env("SENTRY_DSN", default="")
if SENTRY_DSN:
    sentry_sdk.init(
        dsn=SENTRY_DSN,
        environment=env("SENTRY_ENVIRONMENT", default="local"),
        send_default_pii=False,  # never send personal data (SKILLS rule 17)
    )

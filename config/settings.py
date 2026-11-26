"""Django settings. Everything environment-specific comes from env vars (django-environ)."""

from pathlib import Path

import dj_database_url
import environ

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env()
# A local .env is optional (git-ignored); real environments set variables directly.
environ.Env.read_env(BASE_DIR / ".env", overwrite=False)

DEBUG = env.bool("DEBUG", default=env.bool("DJANGO_DEBUG", default=False))
SECRET_KEY = env.str(
    "SECRET_KEY",
    default=env.str("DJANGO_SECRET_KEY", default="dev-only-insecure-key-change-me" if DEBUG else ""),
)
if not SECRET_KEY:
    raise RuntimeError("SECRET_KEY or DJANGO_SECRET_KEY must be set when DEBUG is false.")
ALLOWED_HOSTS = env.list(
    "ALLOWED_HOSTS",
    default=env.list("DJANGO_ALLOWED_HOSTS", default=["localhost", "127.0.0.1"]),
)

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "django.contrib.messages",
    "django.contrib.sessions",
    "django.contrib.staticfiles",
    "rest_framework",
    "drf_spectacular",
    "corsheaders",
    "django_filters",
    # Project apps (ERD s5). `accounts` holds the custom user model.
    "accounts",
    "roles",
    "branches",
    "branch_access",
    "inventory",
    "stock_ledger",
    "warehouse",
    "transfers",
    "sales",
    "audit",
]

AUTH_USER_MODEL = "accounts.User"

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

DATABASES = {
    "default": dj_database_url.config(
        env="DATABASE_URL",
        default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
        conn_max_age=env.int("DB_CONN_MAX_AGE", default=600 if not DEBUG else 60),
    )
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Argon2 first; PBKDF2 stays so any hash made elsewhere can still be verified.
# OQ-13: the only password rule is a 10-character minimum.
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 10}},
]
PASSWORD_MIN_LENGTH = 10
ONE_TIME_PASSWORD_HOURS = 72  # OQ-13
LOGIN_MAX_FAILURES = 5  # per login ID and IP (OQ-13)
LOGIN_WINDOW_MINUTES = 15  # failures counted in this window; the lockout lasts as long
CSRF_FAILURE_VIEW = "config.errors.csrf_failure"

PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
]

# Timestamps are stored in UTC and shown in Africa/Accra. Money is GHS.
LANGUAGE_CODE = "en"
TIME_ZONE = "Africa/Accra"
USE_TZ = True
CURRENCY = "GHS"

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "/media/"
MEDIA_ROOT = Path(
    env.str(
        "MEDIA_ROOT",
        default="/data/media" if not DEBUG else str(BASE_DIR / "media"),
    )
)  # item images; the host picks the disk

STORAGES = {
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.ManifestStaticFilesStorage",
    },
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
}


# Secure sessions and cookies; defaults are strict whenever DEBUG is off.
SESSION_ENGINE = "django.contrib.sessions.backends.db"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = env.str("SESSION_COOKIE_SAMESITE", default="Lax")
SESSION_COOKIE_AGE = env.int("SESSION_COOKIE_AGE", default=60 * 60 * 12)
SESSION_COOKIE_SECURE = env.bool("SESSION_COOKIE_SECURE", default=not DEBUG)
CSRF_COOKIE_SECURE = env.bool("CSRF_COOKIE_SECURE", default=not DEBUG)
CSRF_COOKIE_SAMESITE = env.str("CSRF_COOKIE_SAMESITE", default="Lax")
CSRF_TRUSTED_ORIGINS = env.list(
    "CSRF_TRUSTED_ORIGINS",
    default=env.list("DJANGO_CSRF_TRUSTED_ORIGINS", default=[]),
)
SECURE_SSL_REDIRECT = env.bool("SECURE_SSL_REDIRECT", default=not DEBUG)
SECURE_REDIRECT_EXEMPT = [r"^health/$", r"^/health/$"]  # Railway healthcheck never requires HTTPS redirect
SECURE_HSTS_SECONDS = env.int("SECURE_HSTS_SECONDS", default=0 if DEBUG else 31536000)
SECURE_HSTS_INCLUDE_SUBDOMAINS = env.bool("SECURE_HSTS_INCLUDE_SUBDOMAINS", default=not DEBUG)
SECURE_HSTS_PRELOAD = env.bool("SECURE_HSTS_PRELOAD", default=False)
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"
if not DEBUG or env.bool("SECURE_PROXY_SSL_HEADER_ENABLED", default=False):  # behind the host's HTTPS proxy
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

CORS_ALLOWED_ORIGINS = env.list("CORS_ALLOWED_ORIGINS", default=[])
CORS_EXPOSE_HEADERS = ["Retry-After"]
CORS_ALLOW_ALL_ORIGINS = False
CORS_ALLOW_CREDENTIALS = True

REST_FRAMEWORK = {
    # Deny by default; views opt in. Until a one-time password is changed only /auth/* is open.
    "DEFAULT_AUTHENTICATION_CLASSES": ["accounts.authentication.SessionAuth"],
    "DEFAULT_PERMISSION_CLASSES": [
        "accounts.permissions.IsActiveAccount",
        "accounts.permissions.PasswordChangeNotRequired",
    ],
    "EXCEPTION_HANDLER": "config.errors.exception_handler",
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_PAGINATION_CLASS": "config.pagination.StandardPagination",
    "PAGE_SIZE": 25,
    "DEFAULT_FILTER_BACKENDS": ["django_filters.rest_framework.DjangoFilterBackend"],
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
}

SPECTACULAR_SETTINGS = {
    "TITLE": "Payless4Laptops Inventory API",
    "DESCRIPTION": "Inventory & warehouse system. The OpenAPI contract is the frontend's only link.",
    "VERSION": "0.6.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "ENUM_NAME_OVERRIDES": {
        "BranchTypeEnum": "branches.models.LocationKind",
        "RoleCodeEnum": "accounts.serializers.ROLE_CHOICES",
        "ActionPermissionEnum": "roles.permissions.ACTIONS",
        "PersonPermissionEnum": "roles.constants.PERSON_PERMISSIONS",
        "UserStatusEnum": "accounts.models.UserStatus",
        "ShortfallActionEnum": "transfers.models.ResolutionAction",
        "ItemStatusEnum": "inventory.models.ItemStatus",
        "ItemStatusTargetEnum": "inventory.serializers.STATUS_TARGETS",
        "MovementTypeEnum": "stock_ledger.models.MovementType",
        "ConditionEnum": "inventory.models.Condition",
        "GradeEnum": "inventory.models.Grade",
        "SaleStatusEnum": "sales.models.SaleStatus",
        "UserStatusTargetEnum": "accounts.user_views.STATUS_TARGETS",
    },
}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": env.str("LOG_LEVEL", default="INFO")},
}

# Local-only dev seed passwords (read by manage.py seed_dev, which refuses to run when DEBUG is off).
DEV_SEED_PASSWORDS = {
    "SA": env.str("DEV_SA_0001_PASSWORD", default=""),
    "WA": env.str("DEV_WAREHOUSE_ADMIN_PASSWORD", default=""),
    "BA": env.str("DEV_BRANCH_ADMIN_PASSWORD", default=""),
    "FS": env.str("DEV_FRONT_STAFF_PASSWORD", default=""),
}

# Error monitoring is on only when a DSN is configured.
SENTRY_DSN = env.str("SENTRY_DSN", default="")
if SENTRY_DSN:
    import sentry_sdk

    sentry_sdk.init(
        dsn=SENTRY_DSN,
        environment=env.str("SENTRY_ENVIRONMENT", default="local"),
        # sentry-sdk 3.x dropped include_local_variables/send_default_pii (init raises "Unknown option"); the
        # data_collection option replaces them. Locals may hold passwords or one-time passwords.
        data_collection={
            "user_info": False,
            "stack_frame_variables": False,
            "cookies": {"mode": "off"},
            "http_bodies": [],
        },
    )

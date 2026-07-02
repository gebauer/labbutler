"""Django settings for LabButler.

Configuration is driven entirely by environment variables (see .env.example) so the
same code runs in local dev and in the Docker Compose production stack. No secrets
live in the repo.
"""

from pathlib import Path

import environ
from celery.schedules import crontab

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(
    DJANGO_DEBUG=(bool, False),
    DJANGO_ALLOWED_HOSTS=(list, ["localhost", "127.0.0.1"]),
)

# Read a local .env file if present (dev). In production the env is set by Compose.
env_file = BASE_DIR / ".env"
if env_file.exists():
    env.read_env(str(env_file))

# --- Core -----------------------------------------------------------------------------
DEBUG = env("DJANGO_DEBUG")
if DEBUG:
    SECRET_KEY = env("DJANGO_SECRET_KEY", default="insecure-dev-key-change-me")
else:
    # No fallback outside DEBUG: a known key would let anyone forge session cookies and
    # password-reset tokens. Missing var -> ImproperlyConfigured at startup.
    SECRET_KEY = env("DJANGO_SECRET_KEY")
ALLOWED_HOSTS = env("DJANGO_ALLOWED_HOSTS")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Third-party
    "django_htmx",
    # Local apps
    "apps.tenancy",
    "apps.inventory",
    "apps.procurement",
    "apps.imports",
    "apps.audit",
    "apps.notifications",
    "apps.comments",
    # Login brute-force protection (keep last so it can wrap auth signals).
    "axes",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "labbutler.middleware.ContentSecurityPolicyMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "apps.tenancy.middleware.ImpersonationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "django_htmx.middleware.HtmxMiddleware",
    # Must come last: blocks requests from locked-out clients.
    "axes.middleware.AxesMiddleware",
]

# django-axes checks lockout in an auth backend; ModelBackend still does the real auth.
AUTHENTICATION_BACKENDS = [
    "axes.backends.AxesStandaloneBackend",
    "django.contrib.auth.backends.ModelBackend",
]


def _axes_username(request, credentials):
    """Normalise the login identifier so brute-force counters are case-insensitive.

    Emails are the login field and treated case-insensitively; without this,
    ``Alice@x.de`` and ``alice@x.de`` would get independent lockout allowances.
    """
    username = (credentials or {}).get("username") or request.POST.get("username", "")
    return username.strip().lower()


AXES_USERNAME_CALLABLE = "labbutler.settings._axes_username"

ROOT_URLCONF = "labbutler.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.tenancy.context_processors.labs",
            ],
        },
    },
]

WSGI_APPLICATION = "labbutler.wsgi.application"
ASGI_APPLICATION = "labbutler.asgi.application"

# --- Database -------------------------------------------------------------------------
# JSONB custom fields require PostgreSQL; SQLite is intentionally not supported.
DATABASES = {
    "default": env.db(
        "DATABASE_URL",
        default="postgres://labbutler:labbutler@localhost:5432/labbutler",
    ),
}

# --- Auth -----------------------------------------------------------------------------
AUTH_USER_MODEL = "tenancy.User"

# email is USERNAME_FIELD but intentionally not field-level unique: uniqueness is enforced
# case-insensitively via a Lower("email") UniqueConstraint, which Django's check cannot see.
SILENCED_SYSTEM_CHECKS = ["auth.W004"]

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LOGIN_REDIRECT_URL = "/"
LOGIN_URL = "/accounts/login/"

# Superuser "view as another user". A deployment must opt in explicitly (dev defaults
# on); when disabled the middleware never swaps users and the UI/endpoints are hidden.
LABBUTLER_IMPERSONATION_ENABLED = env.bool("LABBUTLER_IMPERSONATION_ENABLED", default=DEBUG)

# --- I18N / TZ ------------------------------------------------------------------------
LANGUAGE_CODE = "en-us"
TIME_ZONE = env("DJANGO_TIME_ZONE", default="Europe/Berlin")
USE_I18N = True
USE_TZ = True

# --- Static / media -------------------------------------------------------------------
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "labbutler" / "static"]
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

MEDIA_URL = "media/"
MEDIA_ROOT = env("DJANGO_MEDIA_ROOT", default=str(BASE_DIR / "media"))

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Celery / Redis -------------------------------------------------------------------
CELERY_BROKER_URL = env("CELERY_BROKER_URL", default="redis://localhost:6379/0")
CELERY_RESULT_BACKEND = env("CELERY_RESULT_BACKEND", default="redis://localhost:6379/1")
CELERY_TASK_ALWAYS_EAGER = env.bool("CELERY_TASK_ALWAYS_EAGER", default=False)

# Daily digests (run by `celery -A labbutler beat`). Hours are local time.
CELERY_BEAT_SCHEDULE = {
    "expiry-digest-daily": {
        "task": "apps.notifications.tasks.send_expiry_digests",
        "schedule": crontab(hour=env.int("EXPIRY_DIGEST_HOUR", default=7), minute=0),
    },
    "procurement-digest-daily": {
        "task": "apps.notifications.tasks.send_notification_digests",
        "schedule": crontab(hour=env.int("NOTIFY_DIGEST_HOUR", default=7), minute=30),
    },
}

# --- Email ----------------------------------------------------------------------------
EMAIL_BACKEND = env(
    "DJANGO_EMAIL_BACKEND",
    default="django.core.mail.backends.console.EmailBackend",
)
EMAIL_HOST = env("EMAIL_HOST", default="localhost")
EMAIL_PORT = env.int("EMAIL_PORT", default=25)
EMAIL_HOST_USER = env("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", default="")
EMAIL_USE_TLS = env.bool("EMAIL_USE_TLS", default=False)
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="labbutler@localhost")

# --- Notifications --------------------------------------------------------------------
# Absolute base URL used to build links in emails (blank omits links, e.g. in dev).
LABBUTLER_BASE_URL = env("LABBUTLER_BASE_URL", default="")
# How many days ahead the expiry digest looks.
EXPIRY_DIGEST_DAYS = env.int("EXPIRY_DIGEST_DAYS", default=30)

# --- Login brute-force protection (django-axes) ----------------------------------------
AXES_ENABLED = env.bool("AXES_ENABLED", default=True)
# Lock the specific (client IP, username) pair — stops targeted guessing without letting a
# remote attacker lock a victim out globally, or one office IP lock everyone.
AXES_LOCKOUT_PARAMETERS = [["ip_address", "username"]]
AXES_FAILURE_LIMIT = env.int("AXES_FAILURE_LIMIT", default=5)
AXES_COOLOFF_TIME = env.int("AXES_COOLOFF_HOURS", default=1)  # hours before auto-unlock
AXES_RESET_ON_SUCCESS = True
AXES_LOCKOUT_TEMPLATE = "lockout.html"
AXES_HTTP_RESPONSE_CODE = 429
# Behind a reverse proxy set the number of proxies so the *client* IP is used, not the
# proxy's (otherwise everyone shares one IP). 0 = trust REMOTE_ADDR (no proxy).
AXES_IPWARE_PROXY_COUNT = env.int("AXES_IPWARE_PROXY_COUNT", default=0) or None

# --- Security (prod-friendly defaults, relaxed when DEBUG) -----------------------------
# Sent on every response (see labbutler.middleware.ContentSecurityPolicyMiddleware).
# All scripts are vendored and served same-origin, so script-src stays strict; styles
# allow inline because the Django admin still relies on a few inline style attributes.
CONTENT_SECURITY_POLICY = env(
    "DJANGO_CONTENT_SECURITY_POLICY",
    default=(
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; object-src 'none'; frame-ancestors 'none'; "
        "base-uri 'self'; form-action 'self'"
    ),
)

CSRF_TRUSTED_ORIGINS = env("DJANGO_CSRF_TRUSTED_ORIGINS", default=[])
if not DEBUG:
    # Assumes TLS is terminated at a reverse proxy that sets X-Forwarded-Proto.
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_SSL_REDIRECT = env.bool("DJANGO_SECURE_SSL_REDIRECT", default=True)
    SECURE_REDIRECT_EXEMPT = [r"^healthz$"]  # let the container health check use plain HTTP
    SECURE_HSTS_SECONDS = env.int("DJANGO_SECURE_HSTS_SECONDS", default=31536000)  # 1 year
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True

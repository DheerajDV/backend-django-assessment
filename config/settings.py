import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent


def env_bool(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    if value.lower() not in {"0", "1", "false", "true", "no", "yes", "off", "on"}:
        raise ImproperlyConfigured(f"{name} must be a boolean (0/1 or false/true).")
    return value.lower() in {"1", "true", "yes", "on"}


IS_RENDER = env_bool("RENDER")
DEBUG = env_bool("DJANGO_DEBUG", not IS_RENDER)
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "local-assessment-development-key-only")
if not DEBUG and (
    len(SECRET_KEY) < 50 or len(set(SECRET_KEY)) < 5 or SECRET_KEY.startswith("django-insecure-")
):
    raise ImproperlyConfigured(
        "Set DJANGO_SECRET_KEY to a random secret of at least 50 characters."
    )

ALLOWED_HOSTS = [
    host.strip()
    for host in os.environ.get(
        "DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,[::1]" if DEBUG else ""
    ).split(",")
    if host.strip()
]
if render_hostname := os.environ.get("RENDER_EXTERNAL_HOSTNAME"):
    ALLOWED_HOSTS.append(render_hostname)
if not DEBUG and (
    not ALLOWED_HOSTS or any("*" in host or host.startswith(".") for host in ALLOWED_HOSTS)
):
    raise ImproperlyConfigured("Set exact DJANGO_ALLOWED_HOSTS or RENDER_EXTERNAL_HOSTNAME.")

# Render sets RENDER=true and strips/sets forwarded headers at its HTTPS edge.
# On other hosts, enable this only behind a proxy you control and trust.
TRUST_PROXY_HEADERS = env_bool("DJANGO_TRUST_PROXY_HEADERS", IS_RENDER)
if TRUST_PROXY_HEADERS:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = env_bool("DJANGO_SECURE_SSL_REDIRECT", not DEBUG)
# Render probes readiness over HTTP; a redirect would hide database failures.
SECURE_REDIRECT_EXEMPT = [r"^api/health/$"]
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
SECURE_HSTS_SECONDS = 3600 if not DEBUG else 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = False
SECURE_HSTS_PRELOAD = False

# All mutable files live together, on Render's mounted persistent disk in production.
RUNTIME_DIR = Path(os.environ.get("RUNTIME_DIR", BASE_DIR if DEBUG else BASE_DIR / ".runtime"))
if not RUNTIME_DIR.is_absolute():
    RUNTIME_DIR = BASE_DIR / RUNTIME_DIR
CACHE_DIR = RUNTIME_DIR / ".cache"

INSTALLED_APPS = ["django.contrib.contenttypes", "django.contrib.staticfiles", "planner"]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.middleware.common.CommonMiddleware",
    "planner.middleware.RouteRateLimitMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
ROOT_URLCONF = "config.urls"
TEMPLATES = [{"BACKEND": "django.template.backends.django.DjangoTemplates", "APP_DIRS": True}]
WSGI_APPLICATION = "config.wsgi.application"
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": RUNTIME_DIR / "db.sqlite3",
        "OPTIONS": {"timeout": 20},
    }
}
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.filebased.FileBasedCache",
        "LOCATION": CACHE_DIR,
        "TIMEOUT": 86400,
        "OPTIONS": {"MAX_ENTRIES": 10000},
    }
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
TIME_ZONE = "UTC"
USE_TZ = True
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": (
            "django.contrib.staticfiles.storage.StaticFilesStorage"
            if DEBUG
            else "whitenoise.storage.CompressedManifestStaticFilesStorage"
        )
    },
}
DATA_UPLOAD_MAX_MEMORY_SIZE = 16384
PHOTON_BASE_URL = os.environ.get("PHOTON_BASE_URL", "https://photon.komoot.io")
OSRM_BASE_URL = os.environ.get("OSRM_BASE_URL", "https://routing.openstreetmap.de/routed-car")
UPSTREAM_TIMEOUT = (5, 25)
UPSTREAM_USER_AGENT = os.environ.get(
    "UPSTREAM_USER_AGENT", "SpotterFuelAssessment/0.1 (educational assessment demo)"
)
ROUTE_CACHE_SECONDS = 86400
GEOCODE_CACHE_SECONDS = 30 * 86400
STATION_CORRIDOR_MILES = 1.0
API_RATE_LIMIT_ENABLED = env_bool("API_RATE_LIMIT_ENABLED", not DEBUG)
API_RATE_LIMIT = 10
API_GLOBAL_RATE_LIMIT = 30
API_RATE_WINDOW = 60
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
X_FRAME_OPTIONS = "DENY"

import dj_database_url
from decouple import config

from .base import *  # noqa: F401, F403

DEBUG = False

ALLOWED_HOSTS = config(
    "ALLOWED_HOSTS", cast=lambda v: [h.strip() for h in v.split(",") if h.strip()]
)

DATABASES = {"default": dj_database_url.config(conn_max_age=600, ssl_require=True)}

MIDDLEWARE = [  # noqa: F405
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True

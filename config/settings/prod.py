import os

from .base import *

DEBUG = False

ALLOWED_HOSTS = [h for h in os.environ.get("ALLOWED_HOSTS", "").split(",") if h]

CORS_ALLOWED_ORIGINS = [o for o in os.environ.get("CORS_ALLOWED_ORIGINS", "").split(",") if o]

SECURE_SSL_REDIRECT = True

COOKIE_SECURE = True

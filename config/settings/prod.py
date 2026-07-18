import os

from .base import *

DEBUG = False

ALLOWED_HOSTS = [h for h in os.environ.get("ALLOWED_HOSTS", "").split(",") if h]

SECURE_SSL_REDIRECT = True

COOKIE_SECURE = True

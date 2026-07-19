from .base import *

DEBUG = True

ALLOWED_HOSTS = ["localhost", "127.0.0.1"]

# Default Vite/CRA dev server ports.
CORS_ALLOWED_ORIGINS = [
    "http://localhost:5173",
    "http://localhost:3000",
]

SECURE_SSL_REDIRECT = False

# Cookies over plain http://localhost require secure=False.
# Views read this setting when calling response.set_cookie(...).
COOKIE_SECURE = False

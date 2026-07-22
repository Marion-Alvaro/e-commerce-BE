from .base import *

DEBUG = True

# Additive, unlike base.py/prod.py which replace. The locals are always on, so
# adding a tunnel host (cloudflared, for PayMongo webhooks) to ALLOWED_HOSTS
# can never silently lock you out of http://localhost. Django's implicit
# DEBUG=True fallback does NOT cover that case — it only applies when
# ALLOWED_HOSTS is completely empty, so one tunnel entry would otherwise
# disable it. prod.py keeps replace semantics and fails closed.
# dict.fromkeys dedupes while preserving order, in case .env repeats a local.
ALLOWED_HOSTS = list(dict.fromkeys(["localhost", "127.0.0.1"] + ALLOWED_HOSTS))

# CORS_ALLOWED_ORIGINS comes from base.py via env_list().

SECURE_SSL_REDIRECT = False

# Cookies over plain http://localhost require secure=False.
# Views read this setting when calling response.set_cookie(...).
COOKIE_SECURE = False

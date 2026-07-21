"""
ASGI config for config project.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/6.0/howto/deployment/asgi/
"""

import os

from django.core.asgi import get_asgi_application
from dotenv import load_dotenv

load_dotenv()
# Fails safe (prod-hardened) if unset, rather than silently booting with
# DEBUG=True/COOKIE_SECURE=False. Local dev sets DJANGO_SETTINGS_MODULE
# in .env instead of relying on this default.
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.prod')

application = get_asgi_application()

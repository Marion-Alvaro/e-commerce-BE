"""
WSGI config for config project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/6.0/howto/deployment/wsgi/
"""

import os

from django.core.wsgi import get_wsgi_application
from dotenv import load_dotenv

load_dotenv()
# Fails safe (prod-hardened) if unset, rather than silently booting with
# DEBUG=True/COOKIE_SECURE=False. Local dev sets DJANGO_SETTINGS_MODULE
# in .env instead of relying on this default.
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.prod')

application = get_wsgi_application()

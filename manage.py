#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""
import os
import sys


def main():
    """Run administrative tasks."""
    from dotenv import load_dotenv
    load_dotenv()
    # Fails safe (prod-hardened) if unset, rather than silently booting with
    # DEBUG=True/COOKIE_SECURE=False. Local dev sets DJANGO_SETTINGS_MODULE
    # in .env instead of relying on this default.
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.prod')
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == '__main__':
    main()

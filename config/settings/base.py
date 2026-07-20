from pathlib import Path
from dotenv import load_dotenv
import os

from django.core.exceptions import ImproperlyConfigured

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent.parent

SECRET_KEY = os.environ.get('SECRET_KEY')

# Signs the hand-rolled JWT access tokens. Deliberately separate from
# SECRET_KEY (which Django also uses for sessions, password reset tokens,
# etc.) so rotating one never invalidates the other.
ACCESS_TOKEN_SECRET = os.environ.get('ACCESS_TOKEN_SECRET')
if not ACCESS_TOKEN_SECRET:
    # Fail at startup, not on the first jwt.encode() call in production.
    raise ImproperlyConfigured("ACCESS_TOKEN_SECRET environment variable is not set.")


# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    # third-party
    'rest_framework',
    'corsheaders',
    'drf_spectacular',
    # local apps
    'common',
    'accounts',
    'catalog',
    'cart',
    'orders',
]

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'


# Database
# https://docs.djangoproject.com/en/6.0/ref/settings/#databases

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.mysql',
        'NAME': os.environ.get('DB_NAME'),
        'USER': os.environ.get('DB_USER'),
        'PASSWORD': os.environ.get('DB_PASSWORD'),
        'HOST': os.environ.get('DB_HOST', 'localhost'),
        'PORT': os.environ.get('DB_PORT', '3306'),
    }
}


# Password validation
# https://docs.djangoproject.com/en/6.0/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


# Internationalization
# https://docs.djangoproject.com/en/6.0/topics/i18n/

LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'Asia/Manila'

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/6.0/howto/static-files/

STATIC_URL = 'static/'

# Origins populated per-env (dev.py / prod.py). Credentials must be allowed
# for the httponly auth cookies to be sent/received cross-origin from the
# React frontend — a wildcard origin is rejected by browsers once this is on.
CORS_ALLOWED_ORIGINS = []
CORS_ALLOW_CREDENTIALS = True

AUTH_USER_MODEL = "accounts.CustomUser"

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'accounts.authentication.CookieJWTAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 20,
    # drf-spectacular introspects views through this to build the OpenAPI schema.
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
}

# drf-spectacular renders this Markdown at the top of the Swagger/ReDoc page.
# It is the first thing a reader sees, so it explains the one thing the schema
# cannot show on its own: how cookie-JWT auth actually works in this UI.
_API_DESCRIPTION = """\
Products, cart, orders, and **cookie-JWT** authentication.

### How authentication works
`POST /api/auth/register/` and `POST /api/auth/login/` set three cookies:

- `access_token` (**httponly**) — proves who you are on protected requests.
- `refresh_token` (**httponly**, scoped to `/api/auth/`) — used to rotate tokens.
- `csrf_token` (**readable**) — echoed back as a header to defeat CSRF.

The browser attaches these cookies to later same-origin requests automatically,
so there is no `Authorization: Bearer` header to manage.

### Trying it out in Swagger
1. Expand **`POST /api/auth/login/`**, click **Try it out**, send valid credentials.
2. The browser now holds the `access_token` cookie. Call any protected route and
   it authenticates automatically — no further setup.

> **Ignore the green "Authorize" button for auth.** The `access_token` cookie is
> httponly, so JavaScript (and therefore Authorize) cannot set it. Logging in via
> *Try it out* is the only way to authenticate here.

### CSRF on state-changing auth calls
`POST /api/auth/refresh/` and `POST /api/auth/logout/` require an **`X-CSRF-Token`**
header whose value is the readable `csrf_token` cookie set at login/refresh.
(Named distinctly from Django's built-in `X-CSRFToken`/`csrftoken` so Swagger's
auto-CSRF injection can't clobber the value you send.)
"""

SPECTACULAR_SETTINGS = {
    'TITLE': 'E-commerce API',
    'DESCRIPTION': _API_DESCRIPTION,
    'VERSION': '0.1.0',
    # Keep the raw schema endpoint out of the Swagger UI's operation list.
    'SERVE_INCLUDE_SCHEMA': False,
    # Fix the group order and describe each group. Without explicit tags,
    # drf-spectacular auto-tags off a path segment, which leaves these nested
    # routes ungrouped — the views set matching tags=[...] explicitly.
    'TAGS': [
        {'name': 'Authentication', 'description': 'Register, login, token refresh, logout (cookie-JWT).'},
        {'name': 'Catalog', 'description': 'Product listing, search, and admin-only writes.'},
    ],
    'SWAGGER_UI_SETTINGS': {
        # Remember the "Authorize" state across page reloads in the browser.
        'persistAuthorization': True,
        # Show how long each "Try it out" call took.
        'displayRequestDuration': True,
        # Start with operations collapsed to a scannable one-line-per-route list.
        'docExpansion': 'list',
    },
}

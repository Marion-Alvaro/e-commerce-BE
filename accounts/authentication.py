import jwt
from django.contrib.auth import get_user_model
from drf_spectacular.extensions import OpenApiAuthenticationExtension
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed

from common import jwt_utils

User = get_user_model()


class CookieJWTAuthentication(BaseAuthentication):
    def authenticate(self, request):
        token = request.COOKIES.get("access_token")
        if not token:
            # No credentials attempted: let DRF fall through to AllowAny/
            # IsAuthenticated to decide, rather than raising here.
            return None

        try:
            payload = jwt_utils.decode(token)
        except jwt.ExpiredSignatureError:
            raise AuthenticationFailed("Access token expired.")
        except jwt.InvalidTokenError:
            raise AuthenticationFailed("Invalid access token.")

        user_id = payload.get("user_id")
        if user_id is None:
            raise AuthenticationFailed("Invalid access token.")

        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            raise AuthenticationFailed("User not found.")

        return (user, None)

    def authenticate_header(self, request):
        # Without this, DRF has no header to key off and forces every
        # AuthenticationFailed/NotAuthenticated raised under this
        # authenticator to render as 403 instead of 401. Any non-empty
        # value works — there's no WWW-Authenticate challenge scheme here
        # since credentials live in an httponly cookie, not a header.
        return "Cookie"


class CookieJWTScheme(OpenApiAuthenticationExtension):
    """Teach drf-spectacular how CookieJWTAuthentication is secured.

    The token lives in an httponly ``access_token`` cookie, so this is an
    apiKey-in-cookie scheme rather than an ``Authorization: Bearer`` header.
    Because the cookie is httponly, Swagger's "Authorize" button cannot set it
    (JS can't write httponly cookies) — instead, calling the login endpoint in
    the UI sets the cookie and the browser attaches it to later same-origin
    requests automatically. This extension exists so the generated schema is
    accurate; it is registered because this module is always imported (it's
    referenced by DEFAULT_AUTHENTICATION_CLASSES).
    """

    target_class = "accounts.authentication.CookieJWTAuthentication"
    name = "cookieAuth"

    def get_security_definition(self, auto_schema):
        return {"type": "apiKey", "in": "cookie", "name": "access_token"}

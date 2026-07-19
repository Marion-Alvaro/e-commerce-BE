import jwt
from django.conf import settings
from django.contrib.auth import get_user_model
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed

User = get_user_model()


class CookieJWTAuthentication(BaseAuthentication):
    def authenticate(self, request):
        token = request.COOKIES.get("access_token")
        if not token:
            # No credentials attempted: let DRF fall through to AllowAny/
            # IsAuthenticated to decide, rather than raising here.
            return None

        try:
            payload = jwt.decode(token, settings.ACCESS_TOKEN_SECRET, algorithms=["HS256"])
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

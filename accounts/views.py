from django.conf import settings
from django.contrib.auth import authenticate
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from . import services
from .permissions import CSRFPermission
from .serializers import LoginSerializer, RegisterSerializer

ACCESS_TOKEN_MAX_AGE = int(services.ACCESS_TOKEN_TTL.total_seconds())
REFRESH_TOKEN_MAX_AGE = int(services.REFRESH_TOKEN_TTL.total_seconds())


def _set_auth_cookies(response, access_token, refresh_token):
    response.set_cookie(
        key="access_token",
        value=access_token,
        max_age=ACCESS_TOKEN_MAX_AGE,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite="Lax",
        path="/",
    )
    # Scoped to the auth namespace: the browser will only ever attach this
    # cookie to /api/auth/* requests (refresh, logout), never to product/
    # cart/order requests. Scoping it to /api/auth/refresh/ alone would also
    # exclude /api/auth/logout/, which needs to read it to revoke the token
    # family on logout.
    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        max_age=REFRESH_TOKEN_MAX_AGE,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite="Lax",
        path="/api/auth/",
    )
    response.set_cookie(
        key="csrftoken",
        value=services.generate_csrf_token(),
        max_age=REFRESH_TOKEN_MAX_AGE,
        httponly=False,
        secure=settings.COOKIE_SECURE,
        samesite="Lax",
        path="/",
    )


def _clear_auth_cookies(response):
    response.delete_cookie("access_token", path="/")
    response.delete_cookie("refresh_token", path="/api/auth/")
    response.delete_cookie("csrftoken", path="/")


def _user_payload(user):
    return {"id": user.id, "email": user.email, "role": user.role}


@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def register(request):
    serializer = RegisterSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    user = serializer.save()

    access_token = services.generate_access_token(user)
    refresh_token = services.generate_refresh_token(user)

    response = Response(_user_payload(user), status=201)
    _set_auth_cookies(response, access_token, refresh_token)
    return response


@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def login(request):
    serializer = LoginSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    user = authenticate(
        request,
        username=serializer.validated_data["email"],
        password=serializer.validated_data["password"],
    )
    if user is None:
        # Deliberately generic: distinguishing "no such email" from "wrong
        # password" leaks which emails are registered.
        raise AuthenticationFailed("Invalid email or password.")

    access_token = services.generate_access_token(user)
    refresh_token = services.generate_refresh_token(user)

    response = Response(_user_payload(user))
    _set_auth_cookies(response, access_token, refresh_token)
    return response


@api_view(["POST"])
@authentication_classes([])
@permission_classes([CSRFPermission])
def refresh(request):
    raw_refresh_token = request.COOKIES.get("refresh_token")
    if not raw_refresh_token:
        raise AuthenticationFailed("Refresh token missing.")

    user, new_refresh_token = services.rotate_refresh_token(raw_refresh_token)
    access_token = services.generate_access_token(user)

    response = Response({"detail": "Token refreshed."})
    _set_auth_cookies(response, access_token, new_refresh_token)
    return response


@api_view(["POST"])
@permission_classes([IsAuthenticated, CSRFPermission])
def logout(request):
    raw_refresh_token = request.COOKIES.get("refresh_token")
    if raw_refresh_token:
        family_id = services.get_family_id_for_token(raw_refresh_token)
        if family_id:
            services.revoke_token_family(family_id)

    response = Response({"detail": "Logged out."})
    _clear_auth_cookies(response)
    return response

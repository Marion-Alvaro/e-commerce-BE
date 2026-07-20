from django.conf import settings
from django.contrib.auth import authenticate
from drf_spectacular.utils import (
    OpenApiParameter,
    OpenApiResponse,
    extend_schema,
    inline_serializer,
)
from rest_framework import serializers
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from . import services
from .permissions import CSRFPermission
from .serializers import LoginSerializer, RegisterSerializer

ACCESS_TOKEN_MAX_AGE = int(services.ACCESS_TOKEN_TTL.total_seconds())
REFRESH_TOKEN_MAX_AGE = int(services.REFRESH_TOKEN_TTL.total_seconds())

# Shape of the user object returned by register/login (see _user_payload).
_AuthUserResponse = inline_serializer(
    name="AuthUser",
    fields={
        "id": serializers.IntegerField(),
        "email": serializers.EmailField(),
        "role": serializers.CharField(),
    },
)

# DRF renders API errors (AuthenticationFailed, CSRF failures, and non-field
# ValidationErrors) as {"detail": "..."}. One reusable schema documents them all.
_DetailResponse = inline_serializer(
    name="Detail",
    fields={"detail": serializers.CharField()},
)

# Both refresh and logout are guarded by CSRFPermission, which checks this
# header against the readable `csrf_token` cookie set at login. The name is
# intentionally NOT `X-CSRFToken`/`csrftoken` (Django's built-ins) — see
# accounts/permissions.py for why that collision breaks Swagger.
_CSRF_HEADER = OpenApiParameter(
    "X-CSRF-Token",
    str,
    OpenApiParameter.HEADER,
    required=True,
    description="Value of the readable `csrf_token` cookie set at login/refresh.",
)


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
        key="csrf_token",
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
    response.delete_cookie("csrf_token", path="/")


def _user_payload(user):
    return {"id": user.id, "email": user.email, "role": user.role}


@extend_schema(
    tags=["Authentication"],
    summary="Create an account",
    request=RegisterSerializer,
    responses={
        201: _AuthUserResponse,
        400: OpenApiResponse(
            _DetailResponse,
            description="Validation error (e.g. email already registered, weak password, passwords do not match).",
        ),
    },
    description=(
        "Create a new account. On success sets httponly `access_token` and "
        "`refresh_token` cookies (plus a readable `csrf_token`) and returns the user."
    ),
)
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


@extend_schema(
    tags=["Authentication"],
    summary="Log in with email + password",
    request=LoginSerializer,
    responses={
        200: _AuthUserResponse,
        400: OpenApiResponse(_DetailResponse, description="Missing or malformed email/password."),
        401: OpenApiResponse(_DetailResponse, description="Invalid email or password."),
    },
    description=(
        "Authenticate with email + password. On success sets httponly "
        "`access_token` and `refresh_token` cookies (plus a readable `csrf_token`) "
        "and returns the user. After calling this, the browser attaches the "
        "`access_token` cookie to subsequent same-origin requests automatically."
    ),
)
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


@extend_schema(
    tags=["Authentication"],
    summary="Rotate the refresh token",
    request=None,
    parameters=[_CSRF_HEADER],
    responses={
        200: OpenApiResponse(_DetailResponse, description="New access + refresh cookies set."),
        401: OpenApiResponse(
            _DetailResponse,
            description="Refresh token missing, invalid, expired, or reused (family revoked).",
        ),
        403: OpenApiResponse(_DetailResponse, description="CSRF token missing or does not match the cookie."),
    },
    description=(
        "Rotate the refresh-token family using the `refresh_token` cookie and issue "
        "a fresh `access_token`. Requires the `X-CSRF-Token` header."
    ),
)
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


@extend_schema(
    tags=["Authentication"],
    summary="Log out",
    request=None,
    parameters=[_CSRF_HEADER],
    responses={
        200: OpenApiResponse(_DetailResponse, description="Logged out; auth cookies cleared."),
        403: OpenApiResponse(_DetailResponse, description="CSRF token missing or does not match the cookie."),
    },
    description=(
        "Revoke the current refresh-token family and clear the auth cookies. "
        "Does not require a valid access token — only the `X-CSRF-Token` header, "
        "so a session can still be logged out after the access token has expired."
    ),
)
@api_view(["POST"])
@authentication_classes([])
@permission_classes([CSRFPermission])
def logout(request):
    raw_refresh_token = request.COOKIES.get("refresh_token")
    if raw_refresh_token:
        family_id = services.get_family_id_for_token(raw_refresh_token)
        if family_id:
            services.revoke_token_family(family_id)

    response = Response({"detail": "Logged out."})
    _clear_auth_cookies(response)
    return response

import hmac

from rest_framework.permissions import BasePermission

from accounts.models import CustomUser

# Deliberately namespaced away from Django's built-in CSRF (`csrftoken` cookie /
# `X-CSRFToken` header). Reusing Django's names collides with two things that
# silently rewrite them: Django's own CsrfViewMiddleware (which manages the
# `csrftoken` cookie) and drf-spectacular's Swagger UI, whose requestInterceptor
# auto-injects Django's token into the `X-CSRFToken` header on every non-GET
# "Try it out" call — clobbering our value and 403-ing every request.
CSRF_COOKIE_NAME = "csrf_token"
# Django maps the incoming header `X-CSRF-Token` to this META key (uppercase,
# hyphens→underscores, `HTTP_` prefix): X-CSRF-Token → HTTP_X_CSRF_TOKEN. This is
# distinct from Django's HTTP_X_CSRFTOKEN, so nothing injects over it.
CSRF_HEADER_NAME = "HTTP_X_CSRF_TOKEN"


class CSRFPermission(BasePermission):
    """Double-submit cookie check for state-changing requests.

    A malicious site can trigger a cross-origin request that carries the
    browser's cookies automatically, but it cannot read the readable
    csrf_token cookie to also send it as a header — same-origin policy blocks
    that. Requiring the header to match the cookie proves the request
    originated from our own frontend.
    """

    message = "CSRF token missing or invalid."

    def has_permission(self, request, view):
        cookie_token = request.COOKIES.get(CSRF_COOKIE_NAME)
        header_token = request.META.get(CSRF_HEADER_NAME)

        if not cookie_token or not header_token:
            return False

        return hmac.compare_digest(cookie_token, header_token)


class IsAdminRole(BasePermission):
    """Authorization check — must run after IsAuthenticated in the permission list.

    DRF evaluates permission_classes left to right and stops at the first
    failure. If this ran alone against an unauthenticated request,
    request.user would be AnonymousUser and .role would raise AttributeError
    instead of returning a clean 401. Always stack as
    [IsAuthenticated, IsAdminRole].
    """

    message = "Admin role required."

    def has_permission(self, request, view):
        return request.user.role == CustomUser.Role.ADMIN

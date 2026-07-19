import hmac

from rest_framework.permissions import BasePermission

CSRF_COOKIE_NAME = "csrftoken"
CSRF_HEADER_NAME = "HTTP_X_CSRF_TOKEN"


class CSRFPermission(BasePermission):
    """Double-submit cookie check for state-changing requests.

    A malicious site can trigger a cross-origin request that carries the
    browser's cookies automatically, but it cannot read the readable
    csrftoken cookie to also send it as a header — same-origin policy blocks
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

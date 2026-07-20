from django.utils import timezone
from rest_framework.test import APITestCase

DEFAULT_TEST_PASSWORD = "correct-horse-battery-staple"


class AuthenticatedAPITestCase(APITestCase):
    def _login(self, email, password=DEFAULT_TEST_PASSWORD):
        response = self.client.post(
            "/api/auth/login/", {"email": email, "password": password}
        )
        self.assertEqual(response.status_code, 200)
        return response

    def _csrf_headers(self):
        # Send a real `X-CSRF-Token` HTTP header (via headers=) so Django runs its
        # actual header→META conversion instead of us writing request.META directly.
        csrf_token = self.client.cookies["csrf_token"].value
        return {"headers": {"X-CSRF-Token": csrf_token}}

    def _soft_delete(self, instance):
        instance.deleted_at = timezone.now()
        instance.save(update_fields=["deleted_at"])

import jwt
from django.conf import settings
from django.contrib.auth import get_user_model
from rest_framework import serializers as drf_serializers
from rest_framework.test import APITestCase

from .models import RefreshToken
from .serializers import RegisterSerializer

User = get_user_model()

REGISTER_URL = "/api/auth/register/"
LOGIN_URL = "/api/auth/login/"
REFRESH_URL = "/api/auth/refresh/"
LOGOUT_URL = "/api/auth/logout/"


class AuthFlowTests(APITestCase):
    def setUp(self):
        self.password = "correct-horse-battery-staple"
        self.user = User.objects.create_user(
            username="alice",
            email="alice@example.com",
            password=self.password,
        )

    def _login(self):
        response = self.client.post(
            LOGIN_URL, {"email": "alice@example.com", "password": self.password}
        )
        self.assertEqual(response.status_code, 200)
        return response

    def _csrf_headers(self):
        # Send a real `X-CSRF-Token` HTTP header (via headers=) so Django performs
        # its actual header→META conversion. Injecting HTTP_* into the environ
        # directly would bypass that step and hide header-name mismatches.
        csrf_token = self.client.cookies["csrf_token"].value
        return {"headers": {"X-CSRF-Token": csrf_token}}

    def test_register_login_refresh_logout_round_trip(self):
        response = self.client.post(
            REGISTER_URL,
            {
                "email": "bob@example.com",
                "username": "bob",
                "password": "another-strong-pass1",
                "password_confirm": "another-strong-pass1",
            },
        )
        self.assertEqual(response.status_code, 201)
        self.assertIn("access_token", response.cookies)

        response = self.client.post(REFRESH_URL, **self._csrf_headers())
        self.assertEqual(response.status_code, 200)

        response = self.client.post(LOGOUT_URL, **self._csrf_headers())
        self.assertEqual(response.status_code, 200)

    def test_login_with_wrong_password_is_rejected_generically(self):
        response = self.client.post(
            LOGIN_URL, {"email": "alice@example.com", "password": "wrong-password"}
        )
        # DRF returns 403 (not 401) for AuthenticationFailed here because
        # CookieJWTAuthentication doesn't implement authenticate_header().
        self.assertEqual(response.status_code, 403)
        self.assertEqual(str(response.data["detail"]), "Invalid email or password.")

    def test_refresh_without_csrf_header_is_rejected(self):
        self._login()
        response = self.client.post(REFRESH_URL)
        self.assertEqual(response.status_code, 403)

    def test_refresh_with_matching_csrf_header_succeeds(self):
        self._login()
        response = self.client.post(REFRESH_URL, **self._csrf_headers())
        self.assertEqual(response.status_code, 200)

    def test_duplicate_email_register_returns_validation_error_not_500(self):
        response = self.client.post(
            REGISTER_URL,
            {
                "email": "alice@example.com",
                "username": "alice2",
                "password": "another-strong-pass1",
                "password_confirm": "another-strong-pass1",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("email", response.data)

    def test_serializer_create_converts_integrity_error_to_validation_error(self):
        # Bypasses validate_email's pre-check to exercise the IntegrityError
        # fallback in RegisterSerializer.create() directly.
        serializer = RegisterSerializer()
        validated_data = {
            "email": "alice@example.com",
            "username": "alice-duplicate",
            "password": "another-strong-pass1",
            "password_confirm": "another-strong-pass1",
        }
        with self.assertRaises(drf_serializers.ValidationError):
            serializer.create(validated_data)

    def test_refresh_token_reuse_revokes_entire_family(self):
        self._login()
        raw_token_a = self.client.cookies["refresh_token"].value
        family_id = RefreshToken.objects.get(user=self.user).family_id

        response = self.client.post(REFRESH_URL, **self._csrf_headers())
        self.assertEqual(response.status_code, 200)
        raw_token_b = self.client.cookies["refresh_token"].value
        self.assertNotEqual(raw_token_a, raw_token_b)

        # Replay the already-rotated-past token A.
        self.client.cookies["refresh_token"] = raw_token_a
        response = self.client.post(REFRESH_URL, **self._csrf_headers())
        self.assertEqual(response.status_code, 403)

        family_tokens = RefreshToken.objects.filter(family_id=family_id)
        self.assertTrue(family_tokens.exists())
        self.assertTrue(all(token.revoked_at is not None for token in family_tokens))

    def test_malformed_access_token_without_user_id_is_rejected_not_500(self):
        self._login()
        bad_payload = {"role": self.user.role}
        bad_token = jwt.encode(
            bad_payload, settings.ACCESS_TOKEN_SECRET, algorithm="HS256"
        )
        self.client.cookies["access_token"] = bad_token
        response = self.client.post(LOGOUT_URL, **self._csrf_headers())
        self.assertEqual(response.status_code, 401)

import hashlib
import secrets
import uuid
from datetime import timedelta

import jwt
from django.conf import settings
from django.utils import timezone
from rest_framework.exceptions import AuthenticationFailed

from .models import RefreshToken

ACCESS_TOKEN_TTL = timedelta(minutes=15)
REFRESH_TOKEN_TTL = timedelta(days=7)


def generate_access_token(user):
    now = timezone.now()
    payload = {
        "user_id": user.id,
        # Cached for the token's lifetime by design: a role change made mid-session
        # only takes effect once this access token expires (bounded by ACCESS_TOKEN_TTL).
        "role": user.role,
        "iat": now,
        "exp": now + ACCESS_TOKEN_TTL,
    }
    return jwt.encode(payload, settings.ACCESS_TOKEN_SECRET, algorithm="HS256")


def generate_csrf_token():
    return secrets.token_urlsafe(32)


def _hash_token(raw_token):
    return hashlib.sha256(raw_token.encode()).hexdigest()


def generate_refresh_token(user, family_id=None):
    raw_token = secrets.token_urlsafe(64)
    RefreshToken.objects.create(
        user=user,
        token_hash=_hash_token(raw_token),
        family_id=family_id or uuid.uuid4(),
        expires_at=timezone.now() + REFRESH_TOKEN_TTL,
    )
    return raw_token


def rotate_refresh_token(raw_token):
    token_hash = _hash_token(raw_token)
    try:
        stored = RefreshToken.objects.get(token_hash=token_hash)
    except RefreshToken.DoesNotExist:
        raise AuthenticationFailed("Invalid refresh token.")

    if stored.revoked_at is not None:
        # The same refresh token was presented twice: either a replayed request
        # or a stolen token being used after the legitimate client already
        # rotated past it. Either way, the whole device/session chain is now
        # untrustworthy, so kill every token in the family, not just this row.
        revoke_token_family(stored.family_id)
        raise AuthenticationFailed("Refresh token reuse detected; session revoked.")

    if stored.expires_at < timezone.now():
        raise AuthenticationFailed("Refresh token expired.")

    stored.revoked_at = timezone.now()
    stored.save(update_fields=["revoked_at"])

    new_raw_token = generate_refresh_token(stored.user, family_id=stored.family_id)
    return stored.user, new_raw_token


def revoke_token_family(family_id):
    RefreshToken.objects.filter(family_id=family_id, revoked_at__isnull=True).update(
        revoked_at=timezone.now()
    )


def get_family_id_for_token(raw_token):
    token_hash = _hash_token(raw_token)
    try:
        return RefreshToken.objects.get(token_hash=token_hash).family_id
    except RefreshToken.DoesNotExist:
        return None

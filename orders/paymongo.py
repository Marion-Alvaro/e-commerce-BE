"""Thin adapter over the PayMongo REST API.

PayMongo publishes no official Python SDK, so every call is a plain HTTP
request. Keeping those requests here — rather than inline in services.py —
means the business logic in services.py never touches a URL, a header, or a
JSON envelope. That separation is what made the Stripe → PayMongo swap a
one-file change instead of a rewrite of the checkout flow, and it is the
boundary to keep intact if a third provider ever shows up.
"""

import hashlib
import hmac
import time
from base64 import b64encode

import requests
from django.conf import settings

API_BASE = "https://api.paymongo.com/v1"

# PayMongo bills in centavos, matching the integer-cents convention already
# used across the catalog and orders models — no unit conversion needed.
CURRENCY = "PHP"

# The rails a Philippine storefront actually needs. Cards route through 3DS;
# the e-wallets route through their own authorization redirect. Both come
# back to us the same way: a next_action.redirect.url the frontend follows.
PAYMENT_METHODS_ALLOWED = ["card", "gcash", "paymaya", "grab_pay"]

# Any network hiccup must surface as an exception the caller can handle, not
# as a request that hangs a worker thread indefinitely.
TIMEOUT_SECONDS = 15

# How old a webhook's timestamp may be before we refuse it. The signature
# alone proves a payload was authentic once — it does not prove it is being
# delivered now, so without this a captured delivery replays forever. Matches
# the tolerance the Stripe SDK applied for us before the migration; 5 minutes
# is loose enough to absorb clock skew and retry delays.
WEBHOOK_TOLERANCE_SECONDS = 300


class PayMongoError(Exception):
    """Any failed PayMongo call — network, timeout, or non-2xx response."""


def _auth_header(key):
    # PayMongo uses HTTP Basic auth with the API key as the username and an
    # EMPTY password. The trailing colon is not a typo — dropping it produces
    # a different base64 string and a 401 that looks like a bad key.
    token = b64encode(f"{key}:".encode()).decode()
    return {"Authorization": f"Basic {token}", "Content-Type": "application/json"}


def _error_detail(response):
    """Pull PayMongo's structured error out of a failed response.

    requests' own exception string is only "401 Client Error: Unauthorized
    for url: ..." — it drops the body, which is where PayMongo puts the part
    that actually identifies the problem ("amount must be at least 100",
    "API key ... does not exist"). Losing that turns a one-minute fix into an
    hour of guessing, so reach into the body before giving up on it.
    """
    try:
        errors = response.json()["errors"]
    except (ValueError, KeyError, TypeError):
        return response.text[:500]
    return "; ".join(
        f"{e.get('code', 'unknown')}: {e.get('detail', '')}".strip() for e in errors
    )


def _request(method, path, payload=None):
    url = f"{API_BASE}{path}"
    try:
        response = requests.request(
            method,
            url,
            headers=_auth_header(settings.PAYMONGO_SECRET_KEY),
            json=payload,
            timeout=TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        # No response at all — DNS, connection refused, timeout.
        raise PayMongoError(f"{method} {path} failed: {exc}") from exc

    if not response.ok:
        # A response we can read: surface PayMongo's own diagnosis, not just
        # the status line.
        raise PayMongoError(
            f"{method} {path} returned {response.status_code}: {_error_detail(response)}"
        )

    # Every PayMongo resource is wrapped in a top-level "data" envelope.
    return response.json()["data"]


def create_payment_intent(amount_cents, description, metadata=None):
    """Create a PaymentIntent and return the raw resource dict.

    The caller needs two things off the result: `id` (stored on the Order so
    the webhook can match the payment back to it) and `attributes.client_key`
    (handed to the frontend so the browser can attach a payment method to
    this specific intent without ever seeing the secret key).
    """
    attributes = {
        "amount": amount_cents,
        "currency": CURRENCY,
        "payment_method_allowed": PAYMENT_METHODS_ALLOWED,
        "description": description,
    }
    if metadata:
        attributes["metadata"] = metadata
    return _request("POST", "/payment_intents", {"data": {"attributes": attributes}})


def retrieve_payment_intent(intent_id):
    """Fetch an existing PaymentIntent — used to re-hand a client_key to a
    duplicate checkout request instead of creating a second intent."""
    return _request("GET", f"/payment_intents/{intent_id}")


def verify_webhook_signature(raw_body, signature_header, secret):
    """Return True if `raw_body` was signed by PayMongo with `secret`.

    The header looks like:  t=<timestamp>,te=<test_sig>,li=<live_sig>
    Exactly one of te/li carries a value — test mode fills `te` and leaves
    `li` empty, live mode does the reverse. The signed payload is the
    timestamp and the raw body joined by a literal dot, which is why the
    caller must pass request.body and never a re-serialized dict.
    """
    if not (signature_header and secret):
        return False

    try:
        parts = dict(kv.split("=", 1) for kv in signature_header.split(","))
    except ValueError:
        # A malformed header can't be verified — treat it as a failure
        # rather than letting the exception escape as a 500.
        return False

    timestamp = parts.get("t")
    # `or` (not a default) is deliberate: the unused mode's key is present
    # but EMPTY, so .get() alone would hand back "" and fail every compare.
    provided = parts.get("li") or parts.get("te")
    if not (timestamp and provided):
        return False

    signed_payload = f"{timestamp}.".encode() + raw_body
    expected = hmac.new(secret.encode(), signed_payload, hashlib.sha256).hexdigest()

    # compare_digest, not ==: a plain comparison short-circuits on the first
    # differing byte, leaking the correct prefix through response timing.
    if not hmac.compare_digest(expected, provided):
        return False

    # Authenticity established — now check freshness. The timestamp is inside
    # the signed payload, so an attacker replaying a captured delivery cannot
    # move it forward without invalidating the signature. Checked AFTER the
    # HMAC so an unauthenticated caller learns nothing about our clock.
    try:
        age = abs(time.time() - int(timestamp))
    except ValueError:
        return False
    return age <= WEBHOOK_TOLERANCE_SECONDS

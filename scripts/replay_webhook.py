#!/usr/bin/env python
"""Dev tool: send a locally-signed payment.paid webhook to a running server.

This exists so the webhook handler can be exercised without a public tunnel.
It signs the payload with PAYMONGO_WEBHOOK_SECRET from .env exactly the way
PayMongo does, so the real HMAC path in orders/paymongo.py runs.

What it proves:      handler logic, idempotency, stock decrement, cart clearing.
What it does NOT:    that your HMAC matches PayMongo's actual signature, or
                     that a real event carries payment_intent_id where this
                     script puts it. Both signature and payload are fabricated
                     here — only a real delivery through a tunnel confirms
                     those. Treat a pass here as necessary, not sufficient.

Usage (needs the project venv — the shebang resolves to whatever `python` is
on PATH, which is the system interpreter unless the venv is activated):
    .venv/bin/python scripts/replay_webhook.py <payment_intent_id>
    .venv/bin/python scripts/replay_webhook.py <id> --type payment.failed

Get a payment_intent_id by calling POST /api/checkout/ first, or from the
paymongo_pi_id column of any pending order.
"""

import argparse
import hashlib
import hmac
import json
import os
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_URL = "http://localhost:8000/api/webhooks/paymongo/"


def build_event(intent_id, event_type, amount_cents):
    """Mirror the envelope shape from PayMongo's webhook events reference:
    an `event` resource whose attributes.data is the `payment` resource."""
    return {
        "data": {
            "id": f"evt_replay_{int(time.time())}",
            "type": "event",
            "attributes": {
                "type": event_type,
                "livemode": False,
                "created_at": int(time.time()),
                "data": {
                    "id": f"pay_replay_{int(time.time())}",
                    "type": "payment",
                    "attributes": {
                        "amount": amount_cents,
                        "currency": "PHP",
                        "status": "paid" if event_type == "payment.paid" else "failed",
                        "payment_intent_id": intent_id,
                    },
                },
            },
        }
    }


def sign(raw_body, secret, timestamp):
    """Reproduce PayMongo's scheme: HMAC-SHA256 over "<timestamp>.<raw body>".

    Signing the exact bytes that get sent — not a re-serialized dict — is the
    same discipline the handler applies when it reads request.body. If this
    script re-encoded the JSON after signing, the signature would never match,
    which is precisely the bug the handler's comment warns about.
    """
    signature = hmac.new(
        secret.encode(), f"{timestamp}.".encode() + raw_body, hashlib.sha256
    ).hexdigest()
    # te carries the test-mode signature; li is sent but empty in test mode.
    return f"t={timestamp},te={signature},li="


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("intent_id", help="paymongo_pi_id of the order to mark paid")
    parser.add_argument("--type", default="payment.paid", help="event type to send")
    parser.add_argument("--amount", type=int, default=1999, help="amount in centavos")
    parser.add_argument("--url", default=DEFAULT_URL, help="webhook endpoint")
    parser.add_argument(
        "--tamper",
        action="store_true",
        help="sign a different body than the one sent — should be rejected with 400",
    )
    args = parser.parse_args()

    load_dotenv(PROJECT_ROOT / ".env")
    secret = os.environ.get("PAYMONGO_WEBHOOK_SECRET")
    if not secret:
        sys.exit("error: PAYMONGO_WEBHOOK_SECRET not set in .env")

    body = json.dumps(build_event(args.intent_id, args.type, args.amount)).encode()
    signed_body = (
        json.dumps(build_event("pi_something_else", args.type, args.amount)).encode()
        if args.tamper
        else body
    )
    header = sign(signed_body, secret, str(int(time.time())))

    try:
        response = requests.post(
            args.url,
            data=body,
            headers={"Content-Type": "application/json", "Paymongo-Signature": header},
            timeout=10,
        )
    except requests.RequestException as exc:
        sys.exit(f"error: could not reach {args.url} — is runserver up?\n  {exc}")

    print(f"{response.status_code} {response.reason}")
    if response.status_code == 400:
        print("  → rejected. Expected when using --tamper; otherwise check that")
        print("    PAYMONGO_WEBHOOK_SECRET here matches the running server's.")
    elif response.status_code == 200:
        print("  → accepted. Verify the order status and stock actually changed;")
        print("    an unknown intent id is also answered with 200 by design.")


if __name__ == "__main__":
    main()

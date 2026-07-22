#!/usr/bin/env python
"""Dev tool: drive a full PayMongo test payment without a frontend.

Phase 7 (React) doesn't exist yet, so there is nothing to perform the
browser half of the payment flow. This script stands in for it: it logs in,
fills a cart, calls checkout, creates a PaymentMethod, attaches it to the
intent, and prints the authorization URL for you to open.

THIS SCRIPT IS FOR TEST CARDS ONLY, AND ITS SHAPE IS NOT THE PRODUCTION
   PATTERN. It sends card details from here to PayMongo — which is fine for
   a 4343... test number, but in the real system card data must go from the
   customer's BROWSER straight to PayMongo using the PUBLIC key, never
   through your backend or any tool you control. Routing real card numbers
   through your own infrastructure drags you into PCI-DSS scope. When you
   build the React checkout in Phase 7, the browser calls
   POST /v1/payment_methods itself; the backend never sees a card number.

Usage:
    .venv/bin/python scripts/test_payment.py --email you@example.com --password ...

Options:
    --base-url   default http://localhost:8000
    --sku        product to buy; defaults to the first in-stock product
    --card       test card number (default 4343434343434345, succeeds)
"""

import argparse
import json
import os
import sys
from base64 import b64encode
from pathlib import Path

import requests
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PAYMONGO_API = "https://api.paymongo.com/v1"

# Mirrors accounts/permissions.py — deliberately NOT Django's csrftoken /
# X-CSRFToken, so nothing silently rewrites these.
CSRF_COOKIE = "csrf_token"
CSRF_HEADER = "X-CSRF-Token"


def die(step, response):
    print(f"\n✗ {step} failed — HTTP {response.status_code}")
    try:
        print(json.dumps(response.json(), indent=2)[:1500])
    except ValueError:
        print(response.text[:1000])
    sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--sku", help="product SKU to buy (default: first listed)")
    parser.add_argument("--quantity", type=int, default=1)
    parser.add_argument("--card", default="4343434343434345", help="test card number")
    parser.add_argument("--return-url", help="where PayMongo sends you after 3DS")
    args = parser.parse_args()

    load_dotenv(PROJECT_ROOT / ".env")
    public_key = os.environ.get("PAYMONGO_PUBLIC_KEY")
    if not public_key:
        sys.exit("error: PAYMONGO_PUBLIC_KEY not set in .env")

    base = args.base_url.rstrip("/")
    return_url = args.return_url or f"{base}/api/docs/"
    # A session carries the HttpOnly access/refresh cookies automatically,
    # exactly as a browser would.
    session = requests.Session()

    # --- 1. Log in -------------------------------------------------------
    r = session.post(
        f"{base}/api/auth/login/",
        json={"email": args.email, "password": args.password},
        timeout=15,
    )
    if r.status_code != 200:
        die("login", r)
    csrf = session.cookies.get(CSRF_COOKIE)
    if not csrf:
        sys.exit(f"error: login succeeded but no {CSRF_COOKIE} cookie was set")
    # The double-submit check: send the readable cookie back as a header.
    # A cross-origin attacker's page can send the cookie but cannot read it.
    headers = {CSRF_HEADER: csrf}
    print(f"✓ logged in as {args.email}")

    # --- 2. Pick a product and fill the cart -----------------------------
    r = session.get(f"{base}/api/products/", timeout=15)
    if r.status_code != 200:
        die("list products", r)
    body = r.json()
    products = body.get("results", body) if isinstance(body, dict) else body
    if args.sku:
        products = [p for p in products if p.get("sku") == args.sku]
    products = [p for p in products if p.get("stock_quantity", 0) >= args.quantity]
    if not products:
        sys.exit("error: no product with enough stock — create one first")
    product = products[0]
    print(f"✓ product: {product['name']} ({product['sku']}) @ {product['price_cents']} centavos")

    r = session.post(
        f"{base}/api/cart/items/",
        json={"product_id": product["id"], "quantity": args.quantity},
        headers=headers,
        timeout=15,
    )
    if r.status_code not in (200, 201):
        die("add to cart", r)
    print(f"✓ added {args.quantity} to cart")

    # --- 3. Checkout — this is YOUR endpoint -----------------------------
    r = session.post(f"{base}/api/checkout/", headers=headers, timeout=30)
    if r.status_code != 201:
        die("checkout", r)
    checkout = r.json()
    intent_id = checkout["payment_intent_id"]
    client_key = checkout["client_key"]
    print(f"✓ order {checkout['order_id']} created, intent {intent_id}")

    # --- 4. Create a PaymentMethod (browser's job in production) ---------
    pk_auth = {"Authorization": "Basic " + b64encode(f"{public_key}:".encode()).decode()}
    r = requests.post(
        f"{PAYMONGO_API}/payment_methods",
        headers=pk_auth,
        json={
            "data": {
                "attributes": {
                    "type": "card",
                    "details": {
                        "card_number": args.card,
                        "exp_month": 12,
                        "exp_year": 30,
                        "cvc": "123",
                    },
                }
            }
        },
        timeout=30,
    )
    if r.status_code not in (200, 201):
        die("create payment method", r)
    method_id = r.json()["data"]["id"]
    print(f"✓ payment method {method_id}")

    # --- 5. Attach — triggers the charge and the webhook ------------------
    r = requests.post(
        f"{PAYMONGO_API}/payment_intents/{intent_id}/attach",
        headers=pk_auth,
        json={
            "data": {
                "attributes": {
                    "payment_method": method_id,
                    "client_key": client_key,
                    "return_url": return_url,
                }
            }
        },
        timeout=30,
    )
    if r.status_code not in (200, 201):
        die("attach payment method", r)
    attrs = r.json()["data"]["attributes"]
    status = attrs.get("status")
    print(f"✓ attached — intent status: {status}")

    next_action = attrs.get("next_action") or {}
    redirect_url = (next_action.get("redirect") or {}).get("url")
    if redirect_url:
        print("\n→ Open this to complete 3DS authorization:\n")
        print(f"   {redirect_url}\n")
        print("  After authorizing, PayMongo fires payment.paid at your webhook.")
    elif status == "succeeded":
        print("\n  No 3DS step — the payment succeeded immediately.")
    print(f"\n  Then check order {checkout['order_id']}: status should become 'paid'")
    print("  and the product's stock_quantity should drop — via the WEBHOOK,")
    print("  not via this script. That distinction is the whole design.")


if __name__ == "__main__":
    main()

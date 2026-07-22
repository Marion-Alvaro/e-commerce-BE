import hashlib
import hmac
import json
import time
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.test import override_settings

from common.testing import AuthenticatedAPITestCase

from cart.models import Cart, CartItem
from catalog.models import Product
from orders import paymongo
from orders.models import Order, OrderItem

User = get_user_model()

CHECKOUT_URL = "/api/checkout/"
WEBHOOK_URL = "/api/webhooks/paymongo/"

WEBHOOK_SECRET = "whsk_test_secret"


def _fake_payment_intent(pi_id="pi_test_123", client_key="pi_test_123_client_abc"):
    # PayMongo returns plain JSON, not SDK objects, so the fixture is a dict
    # shaped exactly like the real "data" envelope the adapter unwraps.
    return {"id": pi_id, "attributes": {"client_key": client_key}}


class CheckoutTests(AuthenticatedAPITestCase):
    def setUp(self):
        self.customer = User.objects.create_user(
            username="customer",
            email="customer@example.com",
            password="correct-horse-battery-staple",
        )
        self.product = Product.objects.create(
            name="Widget",
            description="A useful widget",
            price_cents=1999,
            stock_quantity=10,
            sku="WIDGET-1",
        )

    def test_checkout_requires_auth(self):
        response = self.client.post(CHECKOUT_URL)
        self.assertEqual(response.status_code, 401)

    def test_checkout_with_empty_cart_is_rejected(self):
        self._login("customer@example.com")
        response = self.client.post(CHECKOUT_URL, **self._csrf_headers())
        self.assertEqual(response.status_code, 400)

    @patch("orders.services.paymongo.create_payment_intent")
    def test_checkout_creates_pending_order_with_snapshotted_items(self, mock_create):
        mock_create.return_value = _fake_payment_intent()

        self._login("customer@example.com")
        cart = Cart.objects.create(user=self.customer)
        CartItem.objects.create(cart=cart, product=self.product, quantity=2)

        response = self.client.post(CHECKOUT_URL, **self._csrf_headers())

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["client_key"], "pi_test_123_client_abc")
        self.assertEqual(response.data["payment_intent_id"], "pi_test_123")

        # The amount sent to PayMongo is the server-computed total, never a
        # client-supplied figure.
        self.assertEqual(mock_create.call_args.kwargs["amount_cents"], 1999 * 2)

        order = Order.objects.get(id=response.data["order_id"])
        self.assertEqual(order.status, Order.Status.PENDING)
        self.assertEqual(order.total_cents, 1999 * 2)
        self.assertEqual(order.paymongo_pi_id, "pi_test_123")

        item = OrderItem.objects.get(order=order)
        self.assertEqual(item.quantity, 2)
        self.assertEqual(item.unit_price_cents, 1999)

        # Price snapshot: changing the product's price afterward must not
        # affect the already-created order.
        self.product.price_cents = 5000
        self.product.save(update_fields=["price_cents"])
        item.refresh_from_db()
        self.assertEqual(item.unit_price_cents, 1999)

    def test_checkout_rejects_insufficient_stock(self):
        self._login("customer@example.com")
        cart = Cart.objects.create(user=self.customer)
        CartItem.objects.create(cart=cart, product=self.product, quantity=self.product.stock_quantity + 1)

        response = self.client.post(CHECKOUT_URL, **self._csrf_headers())

        self.assertEqual(response.status_code, 400)
        self.assertFalse(Order.objects.exists())

    @patch("orders.services.paymongo.retrieve_payment_intent")
    @patch("orders.services.paymongo.create_payment_intent")
    def test_repeated_checkout_reuses_pending_order(self, mock_create, mock_retrieve):
        mock_create.return_value = _fake_payment_intent()
        mock_retrieve.return_value = _fake_payment_intent()

        self._login("customer@example.com")
        cart = Cart.objects.create(user=self.customer)
        CartItem.objects.create(cart=cart, product=self.product, quantity=2)

        first = self.client.post(CHECKOUT_URL, **self._csrf_headers())
        second = self.client.post(CHECKOUT_URL, **self._csrf_headers())

        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 201)
        self.assertEqual(first.data["order_id"], second.data["order_id"])
        self.assertEqual(first.data["client_key"], second.data["client_key"])
        # Only the first call should have hit PayMongo to create a new intent;
        # the second reuses the pending order instead of creating another.
        mock_create.assert_called_once()
        mock_retrieve.assert_called_once()
        self.assertEqual(Order.objects.count(), 1)

    @patch("orders.services.paymongo.create_payment_intent")
    def test_checkout_cancels_order_on_provider_error(self, mock_create):
        mock_create.side_effect = paymongo.PayMongoError("boom")

        self._login("customer@example.com")
        cart = Cart.objects.create(user=self.customer)
        CartItem.objects.create(cart=cart, product=self.product, quantity=2)

        with self.assertLogs("orders.services", level="ERROR") as logs:
            response = self.client.post(CHECKOUT_URL, **self._csrf_headers())

        self.assertEqual(response.status_code, 400)
        order = Order.objects.get()
        self.assertEqual(order.status, Order.Status.CANCELLED)
        self.assertIsNone(order.paymongo_pi_id)

        # The customer sees a deliberately vague message, so the log line is
        # the only record of the real cause — assert it names both the order
        # and the provider's reason.
        self.assertIn(str(order.id), logs.output[0])
        self.assertIn("boom", logs.output[0])
        self.assertNotIn("boom", str(response.data))


@override_settings(PAYMONGO_WEBHOOK_SECRET=WEBHOOK_SECRET)
class PayMongoWebhookTests(AuthenticatedAPITestCase):
    def setUp(self):
        self.customer = User.objects.create_user(
            username="customer",
            email="customer@example.com",
            password="correct-horse-battery-staple",
        )
        self.product = Product.objects.create(
            name="Widget",
            description="A useful widget",
            price_cents=1999,
            stock_quantity=10,
            sku="WIDGET-1",
        )
        self.cart = Cart.objects.create(user=self.customer)
        self.cart_item = CartItem.objects.create(cart=self.cart, product=self.product, quantity=2)
        self.order = Order.objects.create(
            user=self.customer, total_cents=1999 * 2, paymongo_pi_id="pi_test_123"
        )
        OrderItem.objects.create(
            order=self.order,
            product=self.product,
            quantity=2,
            unit_price_cents=1999,
            cart_item=self.cart_item,
        )

    def _event_body(self, pi_id="pi_test_123", event_type="payment.paid"):
        return json.dumps(
            {
                "data": {
                    "id": "evt_test_1",
                    "type": "event",
                    "attributes": {
                        "type": event_type,
                        "livemode": False,
                        "data": {
                            "id": "pay_test_1",
                            "type": "payment",
                            "attributes": {
                                "amount": 1999 * 2,
                                "currency": "PHP",
                                "status": "paid",
                                "payment_intent_id": pi_id,
                            },
                        },
                    },
                }
            }
        )

    def _post(self, body, signature=None, timestamp=None):
        # Signing the body here rather than mocking the verifier means the
        # real HMAC path runs on every webhook test — the security boundary
        # is exercised, not stubbed out. The timestamp defaults to *now*
        # because the verifier enforces a freshness window; a hardcoded
        # constant would start failing the moment it aged past it.
        if timestamp is None:
            timestamp = str(int(time.time()))
        if signature is None:
            expected = hmac.new(
                WEBHOOK_SECRET.encode(),
                f"{timestamp}.".encode() + body.encode(),
                hashlib.sha256,
            ).hexdigest()
            # te = test mode; li is present but empty, as PayMongo sends it.
            signature = f"t={timestamp},te={expected},li="
        return self.client.post(
            WEBHOOK_URL,
            data=body,
            content_type="application/json",
            HTTP_PAYMONGO_SIGNATURE=signature,
        )

    def test_webhook_marks_order_paid_and_decrements_stock(self):
        response = self._post(self._event_body())

        self.assertEqual(response.status_code, 200)

        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.PAID)

        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 8)

        # The cart items this order was built from are cleared.
        self.cart_item.refresh_from_db()
        self.assertIsNotNone(self.cart_item.deleted_at)

    def test_webhook_does_not_clear_unrelated_cart_items(self):
        # Simulates the user adding something new to their cart in the gap
        # between initiating checkout and PayMongo confirming payment.
        other_product = Product.objects.create(
            name="Gadget",
            description="Another product",
            price_cents=999,
            stock_quantity=5,
            sku="GADGET-1",
        )
        unrelated_item = CartItem.objects.create(cart=self.cart, product=other_product, quantity=1)

        response = self._post(self._event_body())

        self.assertEqual(response.status_code, 200)

        self.cart_item.refresh_from_db()
        self.assertIsNotNone(self.cart_item.deleted_at)

        unrelated_item.refresh_from_db()
        self.assertIsNone(unrelated_item.deleted_at)

    def test_webhook_flags_oversold_order_but_still_marks_paid(self):
        # Simulates a stock shortfall discovered only when the webhook
        # fires (e.g. two concurrent checkouts of the last unit).
        self.product.stock_quantity = 1
        self.product.save(update_fields=["stock_quantity"])

        response = self._post(self._event_body())

        self.assertEqual(response.status_code, 200)

        self.order.refresh_from_db()
        # Payment confirmation must never be rolled back by a fulfillment
        # failure — the customer was genuinely charged.
        self.assertEqual(self.order.status, Order.Status.PAID)
        self.assertTrue(self.order.oversold)

        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 1)

    def test_duplicate_webhook_delivery_is_idempotent(self):
        body = self._event_body()
        for _ in range(2):
            self.assertEqual(self._post(body).status_code, 200)

        self.product.refresh_from_db()
        # Stock decremented once, not twice, despite two deliveries of the
        # same event.
        self.assertEqual(self.product.stock_quantity, 8)

    def test_unknown_order_returns_200_to_stop_retries(self):
        response = self._post(self._event_body(pi_id="pi_does_not_exist"))
        self.assertEqual(response.status_code, 200)

    def test_unhandled_event_type_is_acknowledged_without_side_effects(self):
        response = self._post(self._event_body(event_type="payment.failed"))

        self.assertEqual(response.status_code, 200)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.PENDING)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 10)

    def test_invalid_signature_is_rejected(self):
        response = self._post(self._event_body(), signature="t=1700000000,te=deadbeef,li=")
        self.assertEqual(response.status_code, 400)

        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.PENDING)

    def test_missing_signature_header_is_rejected(self):
        response = self._post(self._event_body(), signature="")
        self.assertEqual(response.status_code, 400)

    def test_malformed_signature_header_is_rejected(self):
        # A header that doesn't parse must fail closed, not raise a 500.
        response = self._post(self._event_body(), signature="garbage")
        self.assertEqual(response.status_code, 400)

    def test_tampered_body_is_rejected(self):
        # Sign one body, send another — the classic tamper attempt the HMAC
        # exists to catch.
        body = self._event_body()
        timestamp = str(int(time.time()))
        signature = hmac.new(
            WEBHOOK_SECRET.encode(),
            f"{timestamp}.".encode() + body.encode(),
            hashlib.sha256,
        ).hexdigest()
        tampered = self._event_body(pi_id="pi_attacker")

        response = self._post(
            tampered, signature=f"t={timestamp},te={signature},li="
        )
        self.assertEqual(response.status_code, 400)

    def test_stale_delivery_is_rejected_even_with_a_valid_signature(self):
        # A genuinely-signed payload captured off the wire. The signature is
        # correct forever, so authenticity alone can't reject it — only the
        # freshness window can. The attacker cannot advance the timestamp
        # because it is itself part of the signed payload.
        stale = str(int(time.time()) - paymongo.WEBHOOK_TOLERANCE_SECONDS - 60)
        response = self._post(self._event_body(), timestamp=stale)

        self.assertEqual(response.status_code, 400)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.PENDING)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 10)

    def test_delivery_just_inside_the_tolerance_is_accepted(self):
        # Guards the boundary from the other side: retries and clock skew are
        # normal, so the window must not be so tight that honest deliveries
        # get dropped.
        recent = str(int(time.time()) - paymongo.WEBHOOK_TOLERANCE_SECONDS + 30)
        response = self._post(self._event_body(), timestamp=recent)

        self.assertEqual(response.status_code, 200)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.PAID)

    def test_non_numeric_timestamp_is_rejected(self):
        body = self._event_body()
        signature = hmac.new(
            WEBHOOK_SECRET.encode(), b"abc." + body.encode(), hashlib.sha256
        ).hexdigest()
        response = self._post(body, signature=f"t=abc,te={signature},li=")
        self.assertEqual(response.status_code, 400)


class PayMongoAdapterTests(AuthenticatedAPITestCase):
    """Unit tests for the provider adapter itself — no HTTP, no DB."""

    def _response(self, status, json_body=None, text=""):
        response = Mock()
        response.ok = 200 <= status < 300
        response.status_code = status
        response.text = text
        if json_body is None:
            response.json.side_effect = ValueError("not json")
        else:
            response.json.return_value = json_body
        return response

    @patch("orders.paymongo.requests.request")
    def test_error_message_carries_paymongo_detail(self, mock_request):
        # The whole point: requests' own exception string would only say
        # "422 Client Error", which never identifies the offending field.
        mock_request.return_value = self._response(
            422,
            {
                "errors": [
                    {"code": "parameter_below_minimum", "detail": "amount must be at least 100."}
                ]
            },
        )

        with self.assertRaises(paymongo.PayMongoError) as ctx:
            paymongo.create_payment_intent(50, "Order #1")

        message = str(ctx.exception)
        self.assertIn("parameter_below_minimum", message)
        self.assertIn("amount must be at least 100.", message)
        self.assertIn("422", message)

    @patch("orders.paymongo.requests.request")
    def test_unparseable_error_body_falls_back_to_raw_text(self, mock_request):
        # A gateway 502 returns HTML, not PayMongo's JSON envelope. Falling
        # back to raw text beats raising a KeyError inside the error handler.
        mock_request.return_value = self._response(502, None, text="<html>Bad Gateway</html>")

        with self.assertRaises(paymongo.PayMongoError) as ctx:
            paymongo.create_payment_intent(1000, "Order #1")

        self.assertIn("Bad Gateway", str(ctx.exception))

    @patch("orders.paymongo.requests.request")
    def test_network_failure_becomes_a_provider_error(self, mock_request):
        import requests as requests_lib

        mock_request.side_effect = requests_lib.ConnectionError("connection refused")

        with self.assertRaises(paymongo.PayMongoError) as ctx:
            paymongo.create_payment_intent(1000, "Order #1")

        self.assertIn("connection refused", str(ctx.exception))

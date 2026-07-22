import json
import logging

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.response import Response

from cart.models import CartItem
from catalog.models import Product
from orders import paymongo
from orders.models import Order

logger = logging.getLogger(__name__)


@api_view(["POST"])
# PayMongo is a server making a machine-to-machine POST — no cookies, no user
# session, no CSRF token. The signature check below IS the entire security
# boundary; @csrf_exempt-style bypasses are irrelevant here since this is a
# DRF permission stack, not Django's CSRF middleware.
@authentication_classes([])
@permission_classes([])
def paymongo_webhook(request):
    # request.body, never request.data: the HMAC covers the exact bytes
    # PayMongo sent. Letting DRF parse and re-serialize the JSON reorders
    # keys and normalises whitespace, so the recomputed signature would
    # never match — a failure mode that looks like a wrong secret.
    payload = request.body
    sig_header = request.META.get("HTTP_PAYMONGO_SIGNATURE", "")

    if not paymongo.verify_webhook_signature(
        payload, sig_header, settings.PAYMONGO_WEBHOOK_SECRET
    ):
        # Fails signature — reject outright. Never process an unverified
        # payload.
        return Response(status=400)

    try:
        event = json.loads(payload)["data"]["attributes"]
    except (ValueError, KeyError, TypeError):
        # Signature-valid but structurally unexpected. 400 asks PayMongo to
        # retry, which is right if this was a truncated body.
        return Response(status=400)

    if event.get("type") == "payment.paid":
        # The event wraps the payment resource it describes.
        payment = event["data"]["attributes"]
        # Match on the intent id we stored at checkout rather than on
        # metadata: the intent id is a first-class field of the payment
        # resource, whereas metadata is an echo of what we sent and would
        # silently break the lookup if it were ever dropped or renamed.
        intent_id = payment.get("payment_intent_id")
        if not intent_id:
            logger.error("payment.paid event %s carried no payment_intent_id", event)
            return Response(status=200)

        # Mark the order paid in its own short transaction, separate from
        # the stock decrement below. PayMongo already charged the customer at
        # this point, so a downstream stock failure must never roll this
        # back — payment state and fulfillment state are different concerns.
        with transaction.atomic():
            try:
                order = Order.objects.select_for_update().get(paymongo_pi_id=intent_id)
            except Order.DoesNotExist:
                # Unknown order — return 200 so PayMongo stops retrying a
                # delivery we can never satisfy.
                return Response(status=200)

            if order.status == Order.Status.PAID:
                # PayMongo retries deliveries, so a second delivery of an
                # already-processed event must be a no-op, not a second
                # stock decrement.
                return Response(status=200)

            order.status = Order.Status.PAID
            order.save(update_fields=["status"])

        oversold = False
        for item in order.items.select_related("product"):
            try:
                # Nested atomic() = a savepoint: a constraint violation on
                # one product only rolls back that product's row, not the
                # order.status = PAID write already committed above.
                with transaction.atomic():
                    # select_for_update locks the row so two concurrent
                    # webhook deliveries can't both read-then-write the same
                    # product's stock_quantity. F() then does the
                    # subtraction in SQL rather than Python, so the write
                    # itself is atomic even without the lock — belt and
                    # suspenders.
                    product = Product.objects.select_for_update().get(id=item.product_id)
                    product.stock_quantity = F("stock_quantity") - item.quantity
                    product.save(update_fields=["stock_quantity"])
            except IntegrityError:
                # stock_quantity would go negative (CheckConstraint) — the
                # checkout-time stock check narrows this window but can't
                # close it under concurrent checkouts. The customer is
                # already charged, so surface this for manual refund/
                # backorder handling instead of failing the webhook.
                oversold = True
                logger.critical(
                    "Oversold product %s on order %s: paid but insufficient stock",
                    item.product_id,
                    order.id,
                )

        if oversold:
            order.oversold = True
            order.save(update_fields=["oversold"])

        # Clear only the cart items this order was built from — not the
        # user's whole current cart, which may have grown since checkout
        # was initiated (payment confirmation can take seconds to minutes).
        cart_item_ids = order.items.exclude(cart_item_id=None).values_list(
            "cart_item_id", flat=True
        )
        CartItem.objects.filter(id__in=list(cart_item_ids)).update(deleted_at=timezone.now())

    # Always 200 for anything recognized-but-not-acted-on (other event
    # types) — only a genuine processing error should return non-200 and
    # trigger a PayMongo retry.
    return Response(status=200)

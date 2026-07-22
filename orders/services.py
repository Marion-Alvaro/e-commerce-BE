import logging

from django.db import transaction
from rest_framework.exceptions import ValidationError

from cart.models import Cart
from catalog.models import Product
from orders import paymongo
from orders.models import Order, OrderItem

logger = logging.getLogger(__name__)


def initiate_checkout(user):
    # A double-submit, client retry, or duplicate request finds the pending
    # order this user already started and hands back the same PaymentIntent
    # instead of creating a second Order + PaymentIntent for the same cart.
    # This doesn't close a true simultaneous-millisecond race (MySQL can't
    # lock a row that doesn't exist yet) — acceptable, since the worst case
    # is an unused second PaymentIntent, not a double charge.
    existing = (
        Order.objects.filter(user=user, status=Order.Status.PENDING)
        .exclude(paymongo_pi_id=None)
        .order_by("-created_at")
        .first()
    )
    if existing:
        intent = paymongo.retrieve_payment_intent(existing.paymongo_pi_id)
        return {
            "client_key": intent["attributes"]["client_key"],
            "payment_intent_id": intent["id"],
            "order_id": existing.id,
        }

    try:
        cart = Cart.objects.get(user=user)
    except Cart.DoesNotExist:
        raise ValidationError({"cart": "Cart is empty."})

    # select_related avoids the N+1 trap: one query for items+products
    # instead of one query per item.product access below.
    items = list(cart.items.select_related("product"))
    if not items:
        raise ValidationError({"cart": "Cart is empty."})

    # Server-side total from current product prices — never trust a
    # client-supplied total.
    total_cents = sum(item.product.price_cents * item.quantity for item in items)

    with transaction.atomic():
        # Lock the product rows so a concurrent checkout/cart-update on the
        # same product can't both read a stale stock figure. This reduces,
        # but doesn't eliminate, the oversell race — the webhook still has
        # to handle a residual shortfall gracefully (see paymongo_webhook).
        products = {
            p.id: p
            for p in Product.objects.select_for_update().filter(
                id__in=[item.product_id for item in items]
            )
        }
        for item in items:
            if products[item.product_id].stock_quantity < item.quantity:
                raise ValidationError(
                    {"cart": f"Not enough stock for {item.product.name}."}
                )

        order = Order.objects.create(user=user, total_cents=total_cents)
        OrderItem.objects.bulk_create(
            [
                OrderItem(
                    order=order,
                    product=item.product,
                    quantity=item.quantity,
                    # Snapshot the price now. If the product's price changes
                    # next week, this order's total must stay what the
                    # customer actually agreed to pay — orders are a
                    # historical record, not a live view of the catalog.
                    unit_price_cents=item.product.price_cents,
                    cart_item=item,
                )
                for item in items
            ]
        )

    # The PayMongo call happens outside the transaction above: it's a network
    # round-trip, and holding a DB transaction/connection open for the
    # duration of an external HTTP call is unnecessary lock contention.
    try:
        intent = paymongo.create_payment_intent(
            amount_cents=total_cents,
            description=f"Order #{order.id}",
            # PayMongo echoes metadata back on the webhook's payment object.
            # The webhook does NOT depend on it (it matches on the intent id
            # stored below) — this is a redundant, human-readable trail for
            # reconciling a payment in the dashboard against an order here.
            metadata={"order_id": str(order.id)},
        )
    except paymongo.PayMongoError as exc:
        # Log before translating: the customer gets a deliberately vague
        # message (never leak provider internals to a client), so this line is
        # the ONLY record of why checkout failed. Without it, orders pile up
        # as CANCELLED with no way to tell a declined card from an expired
        # API key.
        logger.error("PayMongo intent creation failed for order %s: %s", order.id, exc)
        # Unlike Stripe, PayMongo exposes no idempotency-key header, so a
        # timeout after the intent was actually created server-side leaves an
        # orphaned intent on their side. That costs nothing — an unattached
        # intent is never charged — and cancelling the order here keeps our
        # side consistent, which is the part we control.
        order.status = Order.Status.CANCELLED
        order.save(update_fields=["status"])
        raise ValidationError({"cart": "Payment provider error, please retry checkout."})

    # If the process dies between the successful call above and this save,
    # the order is left PENDING with paymongo_pi_id=None — a known, queryable
    # fallback (status=PENDING, paymongo_pi_id__isnull=True) and a candidate
    # for a future cleanup/cancel job, not required today.
    order.paymongo_pi_id = intent["id"]
    order.save(update_fields=["paymongo_pi_id"])

    return {
        "client_key": intent["attributes"]["client_key"],
        "payment_intent_id": intent["id"],
        "order_id": order.id,
    }

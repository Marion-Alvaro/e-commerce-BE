from django.conf import settings
from django.db import models


class Order(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        PAID = "paid", "Paid"
        CANCELLED = "cancelled", "Cancelled"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="orders",
        db_index=True,
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    total_cents = models.IntegerField()
    # null (not '') for "no PaymentIntent yet" — MySQL enforces uniqueness across
    # multiple '' values but allows multiple NULLs, so every pending order needs
    # NULL here, not blank='', to coexist under this unique constraint.
    paymongo_pi_id = models.CharField(
        max_length=255, null=True, blank=True, unique=True, default=None
    )
    # Payment (status) and fulfillment (oversold) are different concerns: a
    # stock shortfall discovered when the webhook fires must never roll back
    # the PAID status, since PayMongo already charged the customer. This flag
    # is the queryable signal for support/ops to refund or backorder.
    oversold = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "orders"


class OrderItem(models.Model):
    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name="items",
        db_index=True,
    )
    product = models.ForeignKey(
        "catalog.Product",
        on_delete=models.PROTECT,
        related_name="order_items",
        db_index=True,
    )
    quantity = models.PositiveIntegerField()
    unit_price_cents = models.IntegerField()
    # Snapshot of the cart row this line item came from, so the webhook can
    # clear exactly the items this order consumed — not the user's whole
    # current cart, which may have grown since checkout was initiated.
    # SET_NULL (not CASCADE): a hard-deleted CartItem shouldn't erase order
    # history, and cart items are soft-deleted anyway under normal operation.
    cart_item = models.ForeignKey(
        "cart.CartItem",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="order_items",
    )

    class Meta:
        db_table = "order_items"

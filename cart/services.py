from django.db import transaction
from rest_framework.exceptions import ValidationError

from cart.models import Cart
from catalog.models import Product


def get_or_create_cart(user):
    cart, _ = Cart.objects.get_or_create(user=user)
    return cart


def add_item_to_cart(cart, product, quantity):
    with transaction.atomic():
        # Row-locked so a concurrent add/update on the same product can't
        # both read the pre-write stock figure and both pass the check.
        product = Product.objects.select_for_update().get(pk=product.pk)

        item = cart.items.filter(product=product).first()
        prospective_quantity = (item.quantity if item else 0) + quantity
        if product.stock_quantity < prospective_quantity:
            raise ValidationError({"quantity": "Not enough stock available."})

        if item:
            item.quantity = prospective_quantity
            item.save(update_fields=["quantity", "updated_at"])
            return item

        return cart.items.create(product=product, quantity=quantity)


def update_item_quantity(cart_item, quantity):
    with transaction.atomic():
        product = Product.objects.select_for_update().get(pk=cart_item.product_id)

        if product.stock_quantity < quantity:
            raise ValidationError({"quantity": "Not enough stock available."})

        cart_item.quantity = quantity
        cart_item.save(update_fields=["quantity", "updated_at"])
        return cart_item


def compute_cart_total_cents(cart):
    # select_related avoids the N+1 trap: one query for items+products
    # instead of one query per item.product access.
    return sum(
        item.product.price_cents * item.quantity
        for item in cart.items.select_related("product")
    )

from rest_framework import serializers

from cart.models import Cart, CartItem
from cart.services import compute_cart_total_cents
from catalog.models import Product


class CartItemProductSerializer(serializers.ModelSerializer):
    class Meta:
        model = Product
        fields = ["id", "name", "price_cents"]


class CartItemSerializer(serializers.ModelSerializer):
    product = CartItemProductSerializer(read_only=True)
    subtotal_cents = serializers.SerializerMethodField()

    class Meta:
        model = CartItem
        fields = ["id", "product", "quantity", "subtotal_cents"]
        read_only_fields = ["id"]

    def get_subtotal_cents(self, item):
        return item.product.price_cents * item.quantity


class AddCartItemSerializer(serializers.Serializer):
    # Scoped to Product.objects (the ActiveManager) — a soft-deleted product
    # can't be added to a cart.
    product_id = serializers.PrimaryKeyRelatedField(
        queryset=Product.objects.all(), source="product"
    )
    quantity = serializers.IntegerField(min_value=1)


class UpdateCartItemSerializer(serializers.Serializer):
    quantity = serializers.IntegerField(min_value=1)


class CartSerializer(serializers.ModelSerializer):
    items = serializers.SerializerMethodField()
    total_cents = serializers.SerializerMethodField()

    class Meta:
        model = Cart
        fields = ["id", "items", "total_cents"]

    def get_items(self, cart):
        items = cart.items.select_related("product")
        return CartItemSerializer(items, many=True).data

    def get_total_cents(self, cart):
        return compute_cart_total_cents(cart)

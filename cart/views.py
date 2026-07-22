from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from cart.models import CartItem
from cart.serializers import (
    AddCartItemSerializer,
    CartItemSerializer,
    CartSerializer,
    UpdateCartItemSerializer,
)
from cart.services import add_item_to_cart, get_or_create_cart, update_item_quantity


@extend_schema(tags=["Cart"])
class CartView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        cart = get_or_create_cart(request.user)
        return Response(CartSerializer(cart).data)


@extend_schema(tags=["Cart"])
class CartItemCreateView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=AddCartItemSerializer)
    def post(self, request):
        serializer = AddCartItemSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        cart = get_or_create_cart(request.user)
        item = add_item_to_cart(
            cart,
            serializer.validated_data["product"],
            serializer.validated_data["quantity"],
        )
        return Response(CartItemSerializer(item).data, status=status.HTTP_201_CREATED)


@extend_schema(tags=["Cart"])
class CartItemDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get_object(self, request, pk):
        # Scoped to the requesting user's own cart — an item belonging to
        # someone else 404s rather than 403ing, so existence isn't leaked.
        return get_object_or_404(CartItem.objects, pk=pk, cart__user=request.user)

    @extend_schema(request=UpdateCartItemSerializer)
    def patch(self, request, pk):
        item = self.get_object(request, pk)
        serializer = UpdateCartItemSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        item = update_item_quantity(item, serializer.validated_data["quantity"])
        return Response(CartItemSerializer(item).data)

    def delete(self, request, pk):
        item = self.get_object(request, pk)
        item.deleted_at = timezone.now()
        item.save(update_fields=["deleted_at"])
        return Response(status=status.HTTP_204_NO_CONTENT)

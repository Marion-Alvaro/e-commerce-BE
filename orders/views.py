from drf_spectacular.utils import OpenApiResponse, extend_schema, inline_serializer
from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import CSRFPermission
from orders.services import initiate_checkout

# Shape of the response body — see initiate_checkout in orders/services.py.
_CheckoutResponse = inline_serializer(
    name="CheckoutResponse",
    fields={
        "client_key": serializers.CharField(),
        "payment_intent_id": serializers.CharField(),
        "order_id": serializers.IntegerField(),
    },
)


@extend_schema(
    tags=["Orders"],
    summary="Checkout the current cart",
    request=None,
    responses={
        201: _CheckoutResponse,
        400: OpenApiResponse(description="Cart is empty."),
        403: OpenApiResponse(description="CSRF token missing or does not match the cookie."),
    },
    description=(
        "Creates a pending Order from the user's current cart, snapshots each line "
        "item's price, and returns a PayMongo PaymentIntent client_key for the "
        "frontend to attach a payment method to. The order is marked paid only when "
        "the PayMongo webhook later confirms payment — never by this endpoint."
    ),
)
class CheckoutView(APIView):
    permission_classes = [IsAuthenticated, CSRFPermission]

    def post(self, request):
        result = initiate_checkout(request.user)
        return Response(result, status=201)

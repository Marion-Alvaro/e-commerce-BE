from django.urls import path

from orders.views import CheckoutView
from orders.webhooks import paymongo_webhook

urlpatterns = [
    path("checkout/", CheckoutView.as_view(), name="checkout"),
    path("webhooks/paymongo/", paymongo_webhook, name="paymongo-webhook"),
]

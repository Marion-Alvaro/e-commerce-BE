from django.db import models
from django.utils import timezone

from common.models import ActiveManager


class Product(models.Model):
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    price_cents = models.IntegerField()
    stock_quantity = models.IntegerField(default=0)
    sku = models.CharField(max_length=100, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    deleted_at = models.DateTimeField(null=True, blank=True, default=None)

    objects = ActiveManager()
    all_objects = models.Manager()

    class Meta:
        db_table = "products"
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(stock_quantity__gte=0),
                name="product_stock_non_negative",
            )
        ]

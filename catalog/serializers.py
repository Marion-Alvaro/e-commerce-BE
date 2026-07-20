from rest_framework import serializers

from catalog.models import Product


class ProductSerializer(serializers.ModelSerializer):
    class Meta:
        model = Product
        fields = [
            "id",
            "name",
            "description",
            "price_cents",
            "stock_quantity",
            "sku",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    # No manual sku-uniqueness check needed: DRF's ModelSerializer builds its
    # automatic UniqueValidator from Product._default_manager, which is
    # `objects` (the ActiveManager) since it's declared first on the model.
    # The auto-generated check already excludes soft-deleted rows.

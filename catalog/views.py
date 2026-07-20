from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import status, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from accounts.permissions import IsAdminRole
from catalog.models import Product
from catalog.serializers import ProductSerializer
from catalog.services import search_products


# Group every product operation under the "Catalog" tag so Swagger renders it
# opposite the "Authentication" group (order set by SPECTACULAR_SETTINGS['TAGS']).
@extend_schema(tags=["Catalog"])
class ProductViewSet(viewsets.ModelViewSet):
    serializer_class = ProductSerializer

    def get_queryset(self):
        # Product.objects is the ActiveManager — soft-deleted rows never
        # appear here, in a listing, a detail lookup, or a search.
        queryset = Product.objects.all()
        return search_products(queryset, self.request.query_params.get("search"))

    def get_permissions(self):
        # list/retrieve stay public; only writes are admin-gated.
        # IsAuthenticated must precede IsAdminRole so an anonymous request
        # gets a clean 401 instead of IsAdminRole raising AttributeError on
        # AnonymousUser.role.
        if self.action in ("create", "update", "partial_update", "destroy"):
            return [IsAuthenticated(), IsAdminRole()]
        return []

    def destroy(self, request, *args, **kwargs):
        # Soft delete: set deleted_at instead of removing the row. Past
        # order_items reference this product; a hard delete would break
        # that foreign key.
        #
        # We also mutate the sku here. MySQL has no partial/conditional
        # unique index (unlike Postgres), so products.sku stays physically
        # unique across ALL rows, deleted or not. If we only set deleted_at,
        # the freed-looking SKU is still locked by this dead row, and a new
        # product reusing it fails with a raw IntegrityError (500) even
        # though our app-level ActiveManager-scoped validation says it's
        # fine. Appending a suffix is what actually frees the value at the
        # DB level.
        instance = self.get_object()
        instance.deleted_at = timezone.now()
        instance.sku = f"{instance.sku}-deleted-{instance.deleted_at.timestamp():.0f}"
        instance.save(update_fields=["deleted_at", "sku"])
        return Response(status=status.HTTP_204_NO_CONTENT)

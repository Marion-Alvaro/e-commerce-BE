from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APITestCase

from catalog.models import Product

User = get_user_model()

PRODUCTS_URL = "/api/products/"


def _detail_url(product_id):
    return f"{PRODUCTS_URL}{product_id}/"


class ProductViewSetTests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="admin",
            email="admin@example.com",
            password="correct-horse-battery-staple",
            role=User.Role.ADMIN,
        )
        self.customer = User.objects.create_user(
            username="customer",
            email="customer@example.com",
            password="correct-horse-battery-staple",
        )
        self.product = Product.objects.create(
            name="Widget",
            description="A useful widget",
            price_cents=1999,
            stock_quantity=10,
            sku="WIDGET-1",
        )

    def _login(self, email):
        response = self.client.post(
            "/api/auth/login/", {"email": email, "password": "correct-horse-battery-staple"}
        )
        self.assertEqual(response.status_code, 200)

    def _csrf_headers(self):
        # Send a real `X-CSRF-Token` HTTP header (via headers=) so Django runs its
        # actual header→META conversion instead of us writing request.META directly.
        csrf_token = self.client.cookies["csrf_token"].value
        return {"headers": {"X-CSRF-Token": csrf_token}}

    def _soft_delete(self, product):
        product.deleted_at = timezone.now()
        product.save(update_fields=["deleted_at"])

    def test_list_is_public(self):
        response = self.client.get(PRODUCTS_URL)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)

    def test_retrieve_is_public(self):
        response = self.client.get(_detail_url(self.product.id))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["sku"], "WIDGET-1")

    def test_search_matches_name_and_description(self):
        Product.objects.create(
            name="Gadget", description="unrelated", price_cents=500, stock_quantity=5, sku="GADGET-1"
        )
        response = self.client.get(PRODUCTS_URL, {"search": "widget"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["sku"], "WIDGET-1")

    def test_create_without_auth_is_rejected(self):
        response = self.client.post(PRODUCTS_URL, {
            "name": "New", "price_cents": 100, "stock_quantity": 1, "sku": "NEW-1"
        })
        self.assertEqual(response.status_code, 401)

    def test_create_as_customer_is_forbidden(self):
        self._login("customer@example.com")
        response = self.client.post(
            PRODUCTS_URL,
            {"name": "New", "price_cents": 100, "stock_quantity": 1, "sku": "NEW-1"},
            **self._csrf_headers(),
        )
        self.assertEqual(response.status_code, 403)

    def test_create_as_admin_succeeds(self):
        self._login("admin@example.com")
        response = self.client.post(
            PRODUCTS_URL,
            {"name": "New", "price_cents": 100, "stock_quantity": 1, "sku": "NEW-1"},
            **self._csrf_headers(),
        )
        self.assertEqual(response.status_code, 201)
        self.assertTrue(Product.objects.filter(sku="NEW-1").exists())

    def test_partial_update_as_admin_succeeds(self):
        self._login("admin@example.com")
        response = self.client.patch(
            _detail_url(self.product.id),
            {"price_cents": 2500},
            **self._csrf_headers(),
        )
        self.assertEqual(response.status_code, 200)
        self.product.refresh_from_db()
        self.assertEqual(self.product.price_cents, 2500)

    def test_destroy_is_soft_delete(self):
        self._login("admin@example.com")
        response = self.client.delete(_detail_url(self.product.id), **self._csrf_headers())
        self.assertEqual(response.status_code, 204)

        self.product.refresh_from_db()
        self.assertIsNotNone(self.product.deleted_at)
        # Row still exists — this is a soft delete, not a hard delete.
        self.assertTrue(Product.all_objects.filter(id=self.product.id).exists())

    def test_soft_deleted_product_disappears_from_list_and_search_and_detail(self):
        self._soft_delete(self.product)

        list_response = self.client.get(PRODUCTS_URL)
        self.assertEqual(list_response.data["count"], 0)

        search_response = self.client.get(PRODUCTS_URL, {"search": "widget"})
        self.assertEqual(search_response.data["count"], 0)

        detail_response = self.client.get(_detail_url(self.product.id))
        self.assertEqual(detail_response.status_code, 404)

    def test_sku_uniqueness_excludes_soft_deleted_rows(self):
        # Go through the real DELETE endpoint (not the _soft_delete helper)
        # so the sku-mutation-on-delete logic in destroy() actually runs —
        # that's the piece that frees "WIDGET-1" at the DB level.
        self._login("admin@example.com")
        delete_response = self.client.delete(
            _detail_url(self.product.id), **self._csrf_headers()
        )
        self.assertEqual(delete_response.status_code, 204)

        response = self.client.post(
            PRODUCTS_URL,
            {"name": "Reused SKU", "price_cents": 100, "stock_quantity": 1, "sku": "WIDGET-1"},
            **self._csrf_headers(),
        )
        self.assertEqual(response.status_code, 201)

        self.product.refresh_from_db()
        self.assertNotEqual(self.product.sku, "WIDGET-1")
        self.assertTrue(self.product.sku.startswith("WIDGET-1-deleted-"))

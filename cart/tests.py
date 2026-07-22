from django.contrib.auth import get_user_model

from common.testing import AuthenticatedAPITestCase

from cart.models import CartItem
from catalog.models import Product

User = get_user_model()

CART_URL = "/api/cart/"
CART_ITEMS_URL = "/api/cart/items/"


def _item_url(item_id):
    return f"{CART_ITEMS_URL}{item_id}/"


class CartTests(AuthenticatedAPITestCase):
    def setUp(self):
        self.customer = User.objects.create_user(
            username="customer",
            email="customer@example.com",
            password="correct-horse-battery-staple",
        )
        self.other_customer = User.objects.create_user(
            username="other",
            email="other@example.com",
            password="correct-horse-battery-staple",
        )
        self.product = Product.objects.create(
            name="Widget",
            description="A useful widget",
            price_cents=1999,
            stock_quantity=10,
            sku="WIDGET-1",
        )

    def test_get_cart_requires_auth(self):
        response = self.client.get(CART_URL)
        self.assertEqual(response.status_code, 401)

    def test_get_empty_cart(self):
        self._login("customer@example.com")
        response = self.client.get(CART_URL)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["items"], [])
        self.assertEqual(response.data["total_cents"], 0)

    def test_add_item_creates_new_row(self):
        self._login("customer@example.com")
        response = self.client.post(
            CART_ITEMS_URL,
            {"product_id": self.product.id, "quantity": 2},
            **self._csrf_headers(),
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["quantity"], 2)
        self.assertEqual(CartItem.objects.count(), 1)

    def test_add_same_product_twice_increments_quantity(self):
        self._login("customer@example.com")
        self.client.post(
            CART_ITEMS_URL,
            {"product_id": self.product.id, "quantity": 2},
            **self._csrf_headers(),
        )
        response = self.client.post(
            CART_ITEMS_URL,
            {"product_id": self.product.id, "quantity": 3},
            **self._csrf_headers(),
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(CartItem.objects.count(), 1)
        self.assertEqual(CartItem.objects.first().quantity, 5)

    def test_add_item_over_stock_is_rejected(self):
        self._login("customer@example.com")
        response = self.client.post(
            CART_ITEMS_URL,
            {"product_id": self.product.id, "quantity": 999},
            **self._csrf_headers(),
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(CartItem.objects.exists())

    def test_add_item_over_stock_cumulatively_is_rejected(self):
        self._login("customer@example.com")
        self.client.post(
            CART_ITEMS_URL,
            {"product_id": self.product.id, "quantity": 8},
            **self._csrf_headers(),
        )
        response = self.client.post(
            CART_ITEMS_URL,
            {"product_id": self.product.id, "quantity": 5},
            **self._csrf_headers(),
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(CartItem.objects.first().quantity, 8)

    def test_get_cart_reflects_items_and_total(self):
        self._login("customer@example.com")
        self.client.post(
            CART_ITEMS_URL,
            {"product_id": self.product.id, "quantity": 2},
            **self._csrf_headers(),
        )
        response = self.client.get(CART_URL)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data["items"]), 1)
        self.assertEqual(response.data["total_cents"], 1999 * 2)

    def test_update_item_quantity(self):
        self._login("customer@example.com")
        create_response = self.client.post(
            CART_ITEMS_URL,
            {"product_id": self.product.id, "quantity": 1},
            **self._csrf_headers(),
        )
        item_id = create_response.data["id"]

        response = self.client.patch(
            _item_url(item_id), {"quantity": 4}, **self._csrf_headers()
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["quantity"], 4)

    def test_update_item_over_stock_is_rejected(self):
        self._login("customer@example.com")
        create_response = self.client.post(
            CART_ITEMS_URL,
            {"product_id": self.product.id, "quantity": 1},
            **self._csrf_headers(),
        )
        item_id = create_response.data["id"]

        response = self.client.patch(
            _item_url(item_id), {"quantity": 999}, **self._csrf_headers()
        )
        self.assertEqual(response.status_code, 400)

    def test_update_another_users_item_is_not_found(self):
        self._login("customer@example.com")
        create_response = self.client.post(
            CART_ITEMS_URL,
            {"product_id": self.product.id, "quantity": 1},
            **self._csrf_headers(),
        )
        item_id = create_response.data["id"]

        self._login("other@example.com")
        response = self.client.patch(
            _item_url(item_id), {"quantity": 2}, **self._csrf_headers()
        )
        self.assertEqual(response.status_code, 404)

    def test_delete_item_is_soft_delete(self):
        self._login("customer@example.com")
        create_response = self.client.post(
            CART_ITEMS_URL,
            {"product_id": self.product.id, "quantity": 1},
            **self._csrf_headers(),
        )
        item_id = create_response.data["id"]

        response = self.client.delete(_item_url(item_id), **self._csrf_headers())
        self.assertEqual(response.status_code, 204)

        item = CartItem.all_objects.get(id=item_id)
        self.assertIsNotNone(item.deleted_at)

        cart_response = self.client.get(CART_URL)
        self.assertEqual(cart_response.data["items"], [])

    def test_delete_another_users_item_is_not_found(self):
        self._login("customer@example.com")
        create_response = self.client.post(
            CART_ITEMS_URL,
            {"product_id": self.product.id, "quantity": 1},
            **self._csrf_headers(),
        )
        item_id = create_response.data["id"]

        self._login("other@example.com")
        response = self.client.delete(_item_url(item_id), **self._csrf_headers())
        self.assertEqual(response.status_code, 404)

    def test_cannot_add_soft_deleted_product(self):
        self._soft_delete(self.product)

        self._login("customer@example.com")
        response = self.client.post(
            CART_ITEMS_URL,
            {"product_id": self.product.id, "quantity": 1},
            **self._csrf_headers(),
        )
        self.assertEqual(response.status_code, 400)

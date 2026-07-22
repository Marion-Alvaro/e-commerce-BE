from django.db import migrations


class Migration(migrations.Migration):
    """Rename the payment-provider intent column for the Stripe → PayMongo swap.

    RenameField (not RemoveField + AddField) so the column is renamed in
    place and existing rows keep their intent ids. A drop-and-add would
    silently discard every pending order's link to its payment — recoverable
    on an empty dev database, unrecoverable in production.
    """

    dependencies = [
        ('orders', '0003_order_oversold_orderitem_cart_item'),
    ]

    operations = [
        migrations.RenameField(
            model_name='order',
            old_name='stripe_pi_id',
            new_name='paymongo_pi_id',
        ),
    ]

# order/migrations/0003_alter_order_order_ref_alter_order_subtotal_and_more.py
#
# FIX: Removed the AlterUniqueTogether operation for OrderItem because the
# index order_orderitem_order_id_product_id_1901a4ba_uniq already exists in
# the database (created by a prior migration). Trying to recreate it causes
# sqlite3.OperationalError: index ... already exists.

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('order', '0002_alter_order_delivery_phone_alter_order_order_ref_and_more'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AlterField(
            model_name='order',
            name='order_ref',
            field=models.CharField(db_index=True, editable=False, max_length=20, unique=True),
        ),
        migrations.AlterField(
            model_name='order',
            name='subtotal',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=10),
        ),
        migrations.AlterField(
            model_name='order',
            name='total_amount',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=10),
        ),
        # AlterUniqueTogether for orderitem intentionally omitted —
        # the index already exists in the DB from a prior migration.
    ]
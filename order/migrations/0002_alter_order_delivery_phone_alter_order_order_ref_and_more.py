# Rename this to your next migration number, e.g.:
#   order/migrations/0002_order_delivery_choice.py
# Then update 'dependencies' to reference your actual last migration.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('order', '0001_initial'),   # ← change to your last migration
    ]

    operations = [

        # Delivery mode choice
        migrations.AddField(
            model_name='order',
            name='delivery_choice',
            field=models.CharField(
                max_length=10,
                choices=[
                    ('rider',  'Rider Delivery'),
                    ('pickup', 'Self Pickup'),
                    ('parcel', 'Bus / Parcel'),
                ],
                default='rider',
            ),
        ),

        # Make existing address/city/phone optional
        # (they're blank for pickup/parcel orders)
        migrations.AlterField(
            model_name='order',
            name='delivery_address',
            field=models.TextField(blank=True),
        ),
        migrations.AlterField(
            model_name='order',
            name='delivery_city',
            field=models.CharField(max_length=100, blank=True),
        ),
        migrations.AlterField(
            model_name='order',
            name='delivery_phone',
            field=models.CharField(max_length=20, blank=True),
        ),

        # Parcel fields
        migrations.AddField(
            model_name='order',
            name='parcel_bus_station',
            field=models.CharField(max_length=255, blank=True),
        ),
        migrations.AddField(
            model_name='order',
            name='parcel_recipient_phone',
            field=models.CharField(max_length=20, blank=True),
        ),
        migrations.AddField(
            model_name='order',
            name='parcel_notes',
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name='order',
            name='parcel_waybill',
            field=models.CharField(max_length=100, blank=True),
        ),
        migrations.AddField(
            model_name='order',
            name='parcel_dispatched_at',
            field=models.DateTimeField(null=True, blank=True),
        ),

        # Pickup field
        migrations.AddField(
            model_name='order',
            name='pickup_confirmed_at',
            field=models.DateTimeField(null=True, blank=True),
        ),

        # New 'ready' status for pickup orders
        migrations.AlterField(
            model_name='order',
            name='status',
            field=models.CharField(
                max_length=15,
                choices=[
                    ('pending',    'Pending'),
                    ('confirmed',  'Confirmed'),
                    ('processing', 'Processing'),
                    ('ready',      'Ready for Pickup'),
                    ('dispatched', 'Dispatched'),
                    ('delivered',  'Delivered'),
                    ('cancelled',  'Cancelled'),
                    ('refunded',   'Refunded'),
                ],
                default='pending',
            ),
        ),
    ]
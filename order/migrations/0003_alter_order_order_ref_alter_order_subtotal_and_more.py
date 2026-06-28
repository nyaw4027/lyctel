from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('order', '0002_alter_order_delivery_phone_alter_order_order_ref_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='order',
            name='dropoff_lat',
            field=models.FloatField(null=True, blank=True),
        ),
        migrations.AddField(
            model_name='order',
            name='dropoff_lng',
            field=models.FloatField(null=True, blank=True),
        ),
        migrations.AddField(
            model_name='order',
            name='distance_km',
            field=models.FloatField(null=True, blank=True),
        ),
    ]
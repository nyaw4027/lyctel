from django.db import migrations


class Migration(migrations.Migration):
    """
    Reconcile Django migration state with actual model.
    distance_km, dropoff_lat, dropoff_lng were never in Railway DB
    and were already handled safely in 0004/0006. This removes them
    from Django state so makemigrations stops regenerating this.
    """

    dependencies = [
        ('order', '0006_remove_order_distance_km_remove_order_dropoff_lat_and_more'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.RemoveField(model_name='order', name='distance_km'),
                migrations.RemoveField(model_name='order', name='dropoff_lat'),
                migrations.RemoveField(model_name='order', name='dropoff_lng'),
            ]
        ),
    ]

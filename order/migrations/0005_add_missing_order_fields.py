from django.db import migrations, models, connection


def add_missing_columns(apps, schema_editor):
    columns = [
        ('delivery_choice',        'VARCHAR(10)',                 "'rider'"),
        ('parcel_bus_station',     'TEXT',                        "''"),
        ('parcel_recipient_phone', 'VARCHAR(20)',                 "''"),
        ('parcel_notes',           'TEXT',                        "''"),
        ('parcel_waybill',         'VARCHAR(100)',                "''"),
        ('parcel_dispatched_at',   'TIMESTAMP WITH TIME ZONE',    None),
        ('pickup_confirmed_at',    'TIMESTAMP WITH TIME ZONE',    None),
        ('customer_note',          'TEXT',                        "''"),
        ('admin_note',             'TEXT',                        "''"),
    ]
    with connection.cursor() as cursor:
        if connection.vendor == 'postgresql':
            cursor.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'order_order'")
            existing = {row[0] for row in cursor.fetchall()}
        else:
            cursor.execute("PRAGMA table_info(order_order)")
            existing = {row[1] for row in cursor.fetchall()}
        for col, col_type, default in columns:
            if col not in existing:
                if default is None:
                    cursor.execute(f'ALTER TABLE "order_order" ADD COLUMN "{col}" {col_type} NULL')
                else:
                    cursor.execute(f'ALTER TABLE "order_order" ADD COLUMN "{col}" {col_type} NOT NULL DEFAULT {default}')


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ('order', '0004_remove_order_distance_km_remove_order_dropoff_lat_and_more'),
    ]
    operations = [
        migrations.RunPython(add_missing_columns, noop),
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.AddField(model_name='order', name='delivery_choice', field=models.CharField(choices=[('rider','Rider Delivery'),('pickup','Self Pickup'),('parcel','Bus / Parcel')], default='rider', max_length=10)),
                migrations.AddField(model_name='order', name='parcel_bus_station', field=models.CharField(blank=True, max_length=255)),
                migrations.AddField(model_name='order', name='parcel_recipient_phone', field=models.CharField(blank=True, max_length=20)),
                migrations.AddField(model_name='order', name='parcel_notes', field=models.TextField(blank=True)),
                migrations.AddField(model_name='order', name='parcel_waybill', field=models.CharField(blank=True, max_length=100)),
                migrations.AddField(model_name='order', name='parcel_dispatched_at', field=models.DateTimeField(blank=True, null=True)),
                migrations.AddField(model_name='order', name='pickup_confirmed_at', field=models.DateTimeField(blank=True, null=True)),
                migrations.AddField(model_name='order', name='customer_note', field=models.TextField(blank=True)),
                migrations.AddField(model_name='order', name='admin_note', field=models.TextField(blank=True)),
            ]
        ),
    ]

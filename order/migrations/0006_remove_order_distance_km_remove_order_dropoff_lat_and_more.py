from django.db import migrations, models, connection


def remove_if_exists(apps, schema_editor):
    with connection.cursor() as cursor:
        if connection.vendor == 'postgresql':
            cursor.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'order_order'")
            existing = {row[0] for row in cursor.fetchall()}
        else:
            cursor.execute("PRAGMA table_info(order_order)")
            existing = {row[1] for row in cursor.fetchall()}

    for col in ('distance_km', 'dropoff_lat', 'dropoff_lng'):
        if col in existing:
            with connection.cursor() as cursor:
                cursor.execute(f'ALTER TABLE "order_order" DROP COLUMN IF EXISTS "{col}"')


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('order', '0005_add_missing_order_fields'),
    ]

    operations = [
        migrations.RunPython(remove_if_exists, noop),
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.AlterUniqueTogether(
                    name='orderitem',
                    unique_together={('order', 'product')},
                ),
            ]
        ),
    ]

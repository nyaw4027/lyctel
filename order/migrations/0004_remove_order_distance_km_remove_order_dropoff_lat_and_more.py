from django.db import migrations, models, connection


def remove_fields_if_exist(apps, schema_editor):
    """Safely remove fields only if they exist in the DB — handles broken migration history."""
    with connection.cursor() as cursor:
        # Check which columns actually exist
        cursor.execute("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'order_order'
            AND column_name IN ('distance_km', 'dropoff_lat', 'dropoff_lng')
        """)
        existing = {row[0] for row in cursor.fetchall()}

    for col in ('distance_km', 'dropoff_lat', 'dropoff_lng'):
        if col in existing:
            with connection.cursor() as cursor:
                cursor.execute(f'ALTER TABLE "order_order" DROP COLUMN IF EXISTS "{col}"')


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('order', '0003_alter_order_order_ref_alter_order_subtotal_and_more'),
    ]

    operations = [
        # Safely drop the 3 coordinate fields only if they exist
        migrations.RunPython(remove_fields_if_exist, noop),

        # Alter the fields that the original 0004 also touched
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
    ]
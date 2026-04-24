from django.db.models.signals import post_save
from django.dispatch import receiver

from order.models import Order
from .models import Delivery
from .services import assign_nearest_rider


# ─────────────────────────────
# AUTO CREATE DELIVERY AFTER ORDER
# ─────────────────────────────
@receiver(post_save, sender=Order)
def create_delivery_for_order(sender, instance, created, **kwargs):

    if not created:
        return

    delivery = Delivery.objects.create(
        order=instance,
        delivery_fee=getattr(instance, "delivery_fee", 0),
        zone=getattr(instance, "zone", None)
    )

    # 🔥 AUTO ASSIGN RIDER
    assign_nearest_rider(delivery)
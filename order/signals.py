from django.db.models.signals import post_save
from django.dispatch import receiver

from order.models import Order
from delivery.models import Delivery
from delivery.services import assign_nearest_rider


@receiver(post_save, sender=Order)
def create_delivery_on_payment(sender, instance, created, **kwargs):

    # ✅ Only trigger when order is UPDATED (not created)
    if created:
        return

    # 🔥 ONLY when payment is confirmed
    if instance.payment_status != "paid":
        return

    # 🚨 prevent duplicate delivery
    if hasattr(instance, "delivery"):
        return

    # ─────────────────────────────
    # CREATE DELIVERY
    # ─────────────────────────────
    delivery = Delivery.objects.create(
        order=instance,
        pickup_location="Store / Vendor Location",
        dropoff_location=getattr(instance, "address", ""),
        zone=getattr(instance, "delivery_zone", None),
        distance_km=getattr(instance, "distance_km", None),
        delivery_type="standard",
    )

    # ─────────────────────────────
    # AUTO ASSIGN RIDER
    # ─────────────────────────────
    assign_nearest_rider(delivery)
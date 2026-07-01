"""
order/signals.py

Hooks SMS notifications into Order status changes automatically.
No changes needed in order/views.py or anywhere else — Django's signal
framework fires these the moment any code (staff views, payment webhooks,
admin, etc.) saves an Order with a changed status.

IMPORTANT: Register this in order/apps.py (see instructions below).
"""
from django.db.models.signals import pre_save, post_save
from django.dispatch import receiver

from .models import Order


@receiver(pre_save, sender=Order)
def _stash_previous_status(sender, instance, **kwargs):
    """Stash the current DB status before the save overwrites it."""
    if instance.pk:
        instance._prev_status = (
            Order.objects.filter(pk=instance.pk)
            .values_list('status', flat=True)
            .first()
        )
    else:
        instance._prev_status = None


@receiver(post_save, sender=Order)
def _send_sms_on_status_change(sender, instance, created, **kwargs):
    """
    Fire the matching SMS template whenever the order status transitions
    to a customer-facing milestone. Runs synchronously (no Celery needed).
    """
    prev   = getattr(instance, '_prev_status', None)
    current = instance.status

    # No change, or brand-new order (SMS sent separately when payment
    # is confirmed, not at raw creation time)
    if prev == current:
        return

    # Import here to avoid circular imports at module load time
    from notifications.sms import (
        sms_order_confirmed,
        sms_order_dispatched,
        sms_order_delivered,
        sms_order_cancelled,
    )

    dispatch = {
        Order.Status.CONFIRMED:  sms_order_confirmed,
        Order.Status.DISPATCHED: sms_order_dispatched,
        Order.Status.DELIVERED:  sms_order_delivered,
        Order.Status.CANCELLED:  sms_order_cancelled,
    }

    fn = dispatch.get(current)
    if fn:
        fn(instance)
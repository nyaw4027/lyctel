"""
order/signals.py

Two responsibilities:
1. SMS notifications to the customer on order status transitions.
2. Vendor low-stock SMS alert when any product's stock drops to or
   below its low_stock_alert threshold after a paid order is confirmed.

Register this in order/apps.py (already done).
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
        instance._prev_payment_status = (
            Order.objects.filter(pk=instance.pk)
            .values_list('payment_status', flat=True)
            .first()
        )
    else:
        instance._prev_status = None
        instance._prev_payment_status = None


@receiver(post_save, sender=Order)
def _send_sms_on_status_change(sender, instance, created, **kwargs):
    """
    Fire the matching SMS template whenever the order status transitions
    to a customer-facing milestone.
    """
    prev    = getattr(instance, '_prev_status', None)
    current = instance.status

    if prev == current:
        return

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


@receiver(post_save, sender=Order)
def _vendor_low_stock_alert(sender, instance, created, **kwargs):
    """
    After an order's payment_status transitions to PAID, check every
    product in the order. If any product's stock has dropped to or below
    its low_stock_alert threshold, send the vendor an SMS so they can
    restock before they run out entirely.

    This fires on the same signal as the customer SMS but is keyed on
    payment_status (not order status) so it runs exactly once — when
    payment is confirmed — regardless of subsequent status changes.
    """
    prev_payment = getattr(instance, '_prev_payment_status', None)
    just_paid = (
        instance.payment_status == Order.PaymentStatus.PAID
        and prev_payment != Order.PaymentStatus.PAID
    )
    if not just_paid:
        return

    from notifications.sms import send_sms

    # Group items by vendor so we send one SMS per vendor, not one per item
    vendor_items: dict = {}
    for item in instance.items.select_related('product__vendor').all():
        product = item.product
        if not product or not product.vendor:
            continue
        # Only flag products that are now at or below their own alert threshold
        if product.stock_qty > product.low_stock_alert:
            continue
        vendor = product.vendor
        if vendor not in vendor_items:
            vendor_items[vendor] = []
        vendor_items[vendor].append(product)

    for vendor, low_products in vendor_items.items():
        if not vendor.phone:
            continue
        names = ', '.join(
            f'{p.name} ({p.stock_qty} left)' for p in low_products
        )
        send_sms(
            vendor.phone,
            f'Lynctel: Low stock alert! The following product'
            f'{"s are" if len(low_products) > 1 else " is"} running low '
            f'in your shop: {names}. Please restock soon.',
        )
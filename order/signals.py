"""
order/signals.py

Three responsibilities:
1. Customer SMS on order status transitions.
2. Customer push notification alongside every SMS.
3. Vendor low-stock SMS when stock drops to/below low_stock_alert after payment.
"""
from django.db.models.signals import pre_save, post_save
from django.dispatch import receiver

from .models import Order


@receiver(pre_save, sender=Order)
def _stash_previous_status(sender, instance, **kwargs):
    if instance.pk:
        row = Order.objects.filter(pk=instance.pk).values(
            'status', 'payment_status'
        ).first()
        instance._prev_status         = row['status']         if row else None
        instance._prev_payment_status = row['payment_status'] if row else None
    else:
        instance._prev_status         = None
        instance._prev_payment_status = None


@receiver(post_save, sender=Order)
def _notify_customer_on_status_change(sender, instance, created, **kwargs):
    """SMS + push to customer on every status milestone."""
    prev    = getattr(instance, '_prev_status', None)
    current = instance.status

    if prev == current:
        return

    from notifications.sms import (
        sms_order_confirmed, sms_order_dispatched,
        sms_order_delivered, sms_order_cancelled,
    )
    from push_notifications import (
        push_order_confirmed, push_order_dispatched,
        push_order_delivered, push_order_cancelled,
    )

    sms_map = {
        Order.Status.CONFIRMED:  sms_order_confirmed,
        Order.Status.DISPATCHED: sms_order_dispatched,
        Order.Status.DELIVERED:  sms_order_delivered,
        Order.Status.CANCELLED:  sms_order_cancelled,
    }
    push_map = {
        Order.Status.CONFIRMED:  push_order_confirmed,
        Order.Status.DISPATCHED: push_order_dispatched,
        Order.Status.DELIVERED:  push_order_delivered,
        Order.Status.CANCELLED:  push_order_cancelled,
    }

    if current in sms_map:
        sms_map[current](instance)
    if current in push_map:
        push_map[current](instance)


@receiver(post_save, sender=Order)
def _notify_on_payment_confirmed(sender, instance, created, **kwargs):
    """Push notification to customer the moment payment is confirmed."""
    prev_payment = getattr(instance, '_prev_payment_status', None)
    just_paid = (
        instance.payment_status == Order.PaymentStatus.PAID
        and prev_payment != Order.PaymentStatus.PAID
    )
    if not just_paid:
        return

    from push_notifications import push_payment_confirmed
    push_payment_confirmed(instance)


@receiver(post_save, sender=Order)
def _vendor_low_stock_alert(sender, instance, created, **kwargs):
    """
    After payment is confirmed, SMS any vendor whose products have
    dropped to or below their low_stock_alert threshold.
    Sends one combined SMS per vendor, not one per product.
    """
    prev_payment = getattr(instance, '_prev_payment_status', None)
    just_paid = (
        instance.payment_status == Order.PaymentStatus.PAID
        and prev_payment != Order.PaymentStatus.PAID
    )
    if not just_paid:
        return

    from notifications.sms import send_sms

    vendor_items: dict = {}
    for item in instance.items.select_related('product__vendor').all():
        product = item.product
        if not product or not product.vendor:
            continue
        if product.stock_qty > product.low_stock_alert:
            continue
        vendor = product.vendor
        vendor_items.setdefault(vendor, []).append(product)

    for vendor, products in vendor_items.items():
        if not vendor.phone:
            continue
        names = ', '.join(
            f'{p.name} ({p.stock_qty} left)' for p in products
        )
        send_sms(
            vendor.phone,
            f'Lynctel: Low stock alert! '
            f'{"Products" if len(products) > 1 else "Product"} running low: {names}. '
            f'Restock soon to avoid missed orders.'
        )
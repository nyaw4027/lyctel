"""
order/signals.py

Three responsibilities:
1. Customer SMS + push notification on every order status transition.
2. Push notification when payment is confirmed.
3. Vendor low-stock SMS after a paid order reduces product stock.

Registered via order/apps.py → OrderConfig.ready().
"""
import logging

from django.db.models.signals import pre_save, post_save
from django.dispatch import receiver

from .models import Order

logger = logging.getLogger(__name__)


# ── STASH PREVIOUS VALUES BEFORE SAVE ────────────────────

@receiver(pre_save, sender=Order)
def _stash_previous_values(sender, instance, **kwargs):
    """
    Reads the current DB values before this save overwrites them,
    so post_save can detect what actually changed.
    """
    if instance.pk:
        row = (
            Order.objects
            .filter(pk=instance.pk)
            .values('status', 'payment_status')
            .first()
        )
        instance._prev_status         = row['status']         if row else None
        instance._prev_payment_status = row['payment_status'] if row else None
    else:
        instance._prev_status         = None
        instance._prev_payment_status = None


# ── SMS + PUSH ON STATUS CHANGE ───────────────────────────

@receiver(post_save, sender=Order)
def _notify_customer_on_status_change(sender, instance, created, **kwargs):
    """
    Fires an SMS and a push notification to the customer whenever the
    order status transitions to a meaningful milestone.
    Skips if status hasn't changed.
    """
    prev    = getattr(instance, '_prev_status', None)
    current = instance.status

    if prev == current:
        return

    # SMS
    try:
        from notifications.sms import (
            sms_order_confirmed,
            sms_order_dispatched,
            sms_order_delivered,
            sms_order_cancelled,
        )
        sms_map = {
            Order.Status.CONFIRMED:  sms_order_confirmed,
            Order.Status.DISPATCHED: sms_order_dispatched,
            Order.Status.DELIVERED:  sms_order_delivered,
            Order.Status.CANCELLED:  sms_order_cancelled,
        }
        if current in sms_map:
            sms_map[current](instance)
    except Exception as exc:
        logger.error('[Signals] SMS error on status change: %s', exc)

    # Push notification
    try:
        from push_notifications import (
            push_order_confirmed,
            push_order_dispatched,
            push_order_delivered,
            push_order_cancelled,
        )
        push_map = {
            Order.Status.CONFIRMED:  push_order_confirmed,
            Order.Status.DISPATCHED: push_order_dispatched,
            Order.Status.DELIVERED:  push_order_delivered,
            Order.Status.CANCELLED:  push_order_cancelled,
        }
        if current in push_map:
            push_map[current](instance)
    except Exception as exc:
        logger.error('[Signals] Push error on status change: %s', exc)


# ── PUSH ON PAYMENT CONFIRMED ─────────────────────────────

@receiver(post_save, sender=Order)
def _push_on_payment_confirmed(sender, instance, created, **kwargs):
    """
    Sends a push notification the moment payment transitions to PAID.
    Fires once — not on every save.
    """
    prev_payment = getattr(instance, '_prev_payment_status', None)
    just_paid = (
        instance.payment_status == Order.PaymentStatus.PAID
        and prev_payment != Order.PaymentStatus.PAID
    )
    if not just_paid:
        return

    try:
        from push_notifications import push_payment_confirmed
        push_payment_confirmed(instance)
    except Exception as exc:
        logger.error('[Signals] Push error on payment confirmed: %s', exc)


# ── VENDOR LOW-STOCK SMS AFTER PAYMENT ────────────────────

@receiver(post_save, sender=Order)
def _vendor_low_stock_alert(sender, instance, created, **kwargs):
    """
    After an order's payment is confirmed, checks every product in the
    order. If any product's remaining stock is at or below its own
    low_stock_alert threshold, sends the vendor one combined SMS listing
    all affected products — one message per vendor, not per product.
    """
    prev_payment = getattr(instance, '_prev_payment_status', None)
    just_paid = (
        instance.payment_status == Order.PaymentStatus.PAID
        and prev_payment != Order.PaymentStatus.PAID
    )
    if not just_paid:
        return

    try:
        from notifications.sms import sms_vendor_low_stock

        # Group low-stock products by vendor
        vendor_products: dict = {}
        for item in instance.items.select_related('product__vendor').all():
            product = item.product
            if not product or not product.vendor:
                continue
            # Only flag if now at or below this product's own alert threshold
            if product.stock_qty > product.low_stock_alert:
                continue
            vendor = product.vendor
            vendor_products.setdefault(vendor, []).append(product)

        for vendor, products in vendor_products.items():
            sms_vendor_low_stock(vendor, products)

    except Exception as exc:
        logger.error('[Signals] Low-stock alert error: %s', exc)
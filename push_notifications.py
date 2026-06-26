"""
push_notifications.py
Place at project root (same level as manage.py).
Handles sending Web Push notifications to subscribed users.
"""
import json
from django.conf import settings


def send_push(subscription_info, title, body, url='/', icon=None, badge=None, actions=None):
    """
    Send a push notification to a single subscription.
    subscription_info: dict with keys endpoint, keys.p256dh, keys.auth
    """
    try:
        from pywebpush import webpush, WebPushException

        payload = json.dumps({
            'title':   title,
            'body':    body,
            'url':     url,
            'icon':    icon  or '/static/icons/icon-192x192.png',
            'badge':   badge or '/static/icons/icon-72x72.png',
            'actions': actions or [],
        })

        webpush(
            subscription_info = subscription_info,
            data              = payload,
            vapid_private_key = settings.VAPID_PRIVATE_KEY,
            vapid_claims      = {
                'sub': f'mailto:{settings.VAPID_ADMIN_EMAIL}',
            },
        )
        return True

    except Exception as e:
        # Silently fail — never crash order flow
        return False


def send_push_to_user(user, title, body, url='/', **kwargs):
    """Send push to all active subscriptions for a user."""
    from ecommerce.models import PushSubscription
    subs = PushSubscription.objects.filter(user=user, is_active=True)
    for sub in subs:
        success = send_push(sub.to_dict(), title, body, url, **kwargs)
        if not success:
            # Deactivate broken subscription
            sub.is_active = False
            sub.save(update_fields=['is_active'])


# ── NOTIFICATION TRIGGERS ────────────────────────────────────────────────────

def push_order_confirmed(order):
    if order.customer:
        send_push_to_user(
            order.customer,
            title = '✅ Order Confirmed!',
            body  = f'Order {order.order_ref} is confirmed. GHS {order.total_amount}.',
            url   = f'/orders/{order.order_ref}/track/',
        )

def push_order_dispatched(order):
    if order.customer:
        send_push_to_user(
            order.customer,
            title = '🛵 Rider On The Way!',
            body  = f'Your order {order.order_ref} is out for delivery.',
            url   = f'/orders/{order.order_ref}/track/',
        )

def push_order_delivered(order):
    if order.customer:
        send_push_to_user(
            order.customer,
            title = '🎉 Order Delivered!',
            body  = f'Your order {order.order_ref} has been delivered. Enjoy!',
            url   = f'/orders/{order.order_ref}/track/',
        )

def push_food_confirmed(food_order):
    if food_order.customer:
        send_push_to_user(
            food_order.customer,
            title = '🍔 Food Order Confirmed!',
            body  = f'Your order from {food_order.vendor.name} is confirmed. ETA: {food_order.estimated_delivery_time} mins.',
            url   = f'/food/order/{food_order.order_ref}/',
        )

def push_food_preparing(food_order):
    if food_order.customer:
        send_push_to_user(
            food_order.customer,
            title = '👨‍🍳 Being Prepared!',
            body  = f'{food_order.vendor.name} is preparing your order.',
            url   = f'/food/order/{food_order.order_ref}/',
        )

def push_food_dispatched(food_order):
    if food_order.customer:
        send_push_to_user(
            food_order.customer,
            title = '🛵 Food On The Way!',
            body  = f'Your order from {food_order.vendor.name} is out for delivery!',
            url   = f'/food/order/{food_order.order_ref}/',
        )

def push_food_delivered(food_order):
    if food_order.customer:
        send_push_to_user(
            food_order.customer,
            title = '🎉 Food Delivered!',
            body  = f'Your order from {food_order.vendor.name} has arrived. Enjoy your meal!',
            url   = f'/food/order/{food_order.order_ref}/',
        )

def push_new_order_to_vendor(order):
    """Notify vendor when a new order comes in."""
    try:
        first_item = order.items.select_related('product__vendor').first()
        if first_item and first_item.product and first_item.product.vendor:
            vendor_user = first_item.product.vendor.owner
            send_push_to_user(
                vendor_user,
                title = '🛒 New Order!',
                body  = f'Order {order.order_ref} · GHS {order.total_amount}',
                url   = f'/vendors/dashboard/?tab=orders',
            )
    except Exception:
        pass

def push_new_food_order_to_restaurant(food_order):
    """Notify restaurant owner when a new food order comes in."""
    try:
        send_push_to_user(
            food_order.vendor.owner,
            title = '🍽️ New Food Order!',
            body  = f'{food_order.order_ref} · GHS {food_order.total_amount} · Accept now!',
            url   = '/food/dashboard/?tab=orders',
        )
    except Exception:
        pass

def push_rider_assigned(delivery):
    """Notify rider when assigned a delivery."""
    try:
        if delivery.rider:
            order_ref = ''
            if delivery.order:
                order_ref = delivery.order.order_ref
            elif hasattr(delivery, 'food_order') and delivery.food_order:
                order_ref = delivery.food_order.order_ref

            send_push_to_user(
                delivery.rider.rider,
                title = '🛵 New Delivery!',
                body  = f'Order {order_ref} assigned. Commission: GHS {delivery.rider_commission}',
                url   = '/rider/',
            )
    except Exception:
        pass
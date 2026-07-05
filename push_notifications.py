"""
push_notifications.py

Web Push notification service for Lynctel.
Uses pywebpush (VAPID) to send push messages to subscribed browsers.

Required settings:
    VAPID_PRIVATE_KEY  — your VAPID private key (base64url)
    VAPID_PUBLIC_KEY   — your VAPID public key  (base64url)
    VAPID_ADMIN_EMAIL  — contact email for the VAPID claim

The VAPID public key is already in base.html:
    BAEw351eT-whUPpELa7PRDNEM0E_qzbKy6V9pI2jMjjHIS_JQx6cUj9hPahI9k86eCuG1QntOHnGi_1Yi_fWVwM

Generate a matching key pair (one-time, run in shell):
    from pywebpush import Vapid
    v = Vapid()
    v.generate_keys()
    print(v.private_key.private_bytes_raw().hex())  # → VAPID_PRIVATE_KEY
    print(v.public_key.public_bytes_raw().hex())    # → VAPID_PUBLIC_KEY

Subscribe endpoint: /push/subscribe/
Called automatically by base.html's subscribeToPush() JS function.
"""
import json
import logging

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

logger = logging.getLogger(__name__)


# ── SUBSCRIBE VIEW ────────────────────────────────────────

@login_required
@require_POST
def subscribe(request):
    """
    Stores a push subscription for the logged-in user.
    Called from base.html's subscribeToPush() after the browser grants
    notification permission.
    """
    try:
        data     = json.loads(request.body)
        endpoint = data.get('endpoint', '').strip()
        p256dh   = data.get('keys', {}).get('p256dh', '').strip()
        auth     = data.get('keys', {}).get('auth',   '').strip()

        if not endpoint or not p256dh or not auth:
            return JsonResponse({'error': 'Invalid subscription data'}, status=400)

        from ecommerce.models import PushSubscription
        PushSubscription.objects.update_or_create(
            user     = request.user,
            endpoint = endpoint,
            defaults = {'p256dh': p256dh, 'auth': auth},
        )
        return JsonResponse({'success': True})

    except (json.JSONDecodeError, KeyError) as exc:
        logger.error('[Push] Subscribe error: %s', exc)
        return JsonResponse({'error': 'Bad request'}, status=400)


# ── SEND HELPERS ──────────────────────────────────────────

def send_push_notification(user, title, body, url='/'):
    """
    Sends a push notification to ALL active subscriptions for a given user.
    Returns the number of subscriptions successfully notified.

    Never raises — a push failure should never break the caller
    (e.g. an order status signal).
    """
    try:
        from ecommerce.models import PushSubscription
        subscriptions = PushSubscription.objects.filter(user=user)
    except Exception as exc:
        logger.error('[Push] Could not query subscriptions: %s', exc)
        return 0

    sent = 0
    for sub in subscriptions:
        if _send_to_subscription(sub, title, body, url):
            sent += 1
    return sent


def _send_to_subscription(sub, title, body, url='/'):
    """
    Sends a single push notification to one subscription endpoint.
    Returns True on success, False on any failure.
    Removes the subscription if the browser reports it's expired (410).
    """
    private_key = getattr(settings, 'VAPID_PRIVATE_KEY', None)
    admin_email = getattr(settings, 'VAPID_ADMIN_EMAIL', 'support@lynctel.com')

    if not private_key:
        logger.warning('[Push] VAPID_PRIVATE_KEY not configured — skipping push.')
        return False

    payload = json.dumps({
        'title': title,
        'body':  body,
        'url':   url,
        'icon':  '/static/icons/icon-192x192.png',
        'badge': '/static/icons/icon-96x96.png',
    })

    try:
        from pywebpush import webpush, WebPushException
        webpush(
            subscription_info={
                'endpoint': sub.endpoint,
                'keys': {
                    'p256dh': sub.p256dh,
                    'auth':   sub.auth,
                },
            },
            data=payload,
            vapid_private_key=private_key,
            vapid_claims={
                'sub': f'mailto:{admin_email}',
            },
        )
        return True

    except Exception as exc:
        # 410 Gone = subscription expired, clean it up
        err_str = str(exc)
        if '410' in err_str or 'Gone' in err_str:
            logger.info('[Push] Removing expired subscription for user %s', sub.user_id)
            sub.delete()
        else:
            logger.warning('[Push] Failed to send to endpoint %s: %s', sub.endpoint[:40], exc)
        return False


# ── ORDER-SPECIFIC PUSH TEMPLATES ─────────────────────────

def push_order_confirmed(order):
    return send_push_notification(
        order.customer,
        title='Order Confirmed ✅',
        body=f'Your order {order.order_ref} (GHS {order.total_amount}) is confirmed. Rider being assigned.',
        url=f'/order/{order.order_ref}/track/',
    )


def push_order_dispatched(order):
    return send_push_notification(
        order.customer,
        title='Order On the Way 🛵',
        body=f'Your order {order.order_ref} is on its way! A rider will call on arrival.',
        url=f'/order/{order.order_ref}/track/',
    )


def push_order_delivered(order):
    return send_push_notification(
        order.customer,
        title='Order Delivered 🎉',
        body=f'Your order {order.order_ref} has been delivered. Enjoy!',
        url=f'/order/{order.order_ref}/confirm/',
    )


def push_order_cancelled(order):
    return send_push_notification(
        order.customer,
        title='Order Cancelled',
        body=f'Your order {order.order_ref} was cancelled. Contact support if unexpected.',
        url='/order/',
    )


def push_payment_confirmed(order):
    return send_push_notification(
        order.customer,
        title='Payment Received 💰',
        body=f'GHS {order.total_amount} received for order {order.order_ref}.',
        url=f'/order/{order.order_ref}/confirm/',
    )
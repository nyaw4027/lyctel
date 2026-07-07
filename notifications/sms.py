"""
notifications/sms.py

SMS service via Arkesel (https://arkesel.com).
Reads ARKESEL_API_KEY and ARKESEL_SENDER_ID from settings.

Both keys are already in your .env:
    ARKESEL_API_KEY=UlZDTVpkbHpRamRsdmRBV3diU0o
    ARKESEL_SENDER_ID=Lynctel

And in settings.py:
    ARKESEL_API_KEY   = config('ARKESEL_API_KEY',   default='')
    ARKESEL_SENDER_ID = config('ARKESEL_SENDER_ID', default='Lynctel')

Usage:
    from notifications.sms import send_sms
    send_sms(to='0558040216', message='Your order is confirmed!')
"""
import logging

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

ARKESEL_URL = 'https://sms.arkesel.com/api/v2/sms/send'


def _normalise_phone(phone):
    """
    Normalises a Ghana phone number to the format Arkesel expects.
    Arkesel accepts: 0XXXXXXXXX or 233XXXXXXXXX
    Handles all common formats:
        0558040216      → 0558040216
        +233558040216   → 0558040216
        233558040216    → 0558040216
    """
    if not phone:
        return None

    digits = ''.join(c for c in str(phone) if c.isdigit())

    if digits.startswith('233') and len(digits) == 12:
        return '0' + digits[3:]

    if digits.startswith('0') and len(digits) == 10:
        return digits

    # Unrecognised format — pass through and let Arkesel reject explicitly
    return digits


def send_sms(to, message):
    """
    Sends a single SMS via Arkesel API v2.

    Returns True on success, False on any failure.
    Never raises — a failed SMS must never break the caller
    (e.g. an order status signal or payment webhook).
    """
    api_key   = getattr(settings, 'ARKESEL_API_KEY',   None)
    sender_id = getattr(settings, 'ARKESEL_SENDER_ID', None)

    if not api_key:
        logger.warning('[SMS] ARKESEL_API_KEY not configured — SMS skipped.')
        return False

    if not sender_id:
        logger.warning('[SMS] ARKESEL_SENDER_ID not configured — SMS skipped.')
        return False

    phone = _normalise_phone(to)
    if not phone:
        logger.warning('[SMS] No valid phone number supplied: %r', to)
        return False

    headers = {
        'api-key':      api_key,
        'Content-Type': 'application/json',
        'Accept':       'application/json',
    }

    payload = {
        'sender':     sender_id,
        'message':    message,
        'recipients': [phone],
    }

    try:
        response = requests.post(
            ARKESEL_URL,
            json=payload,
            headers=headers,
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()

        # Arkesel returns {"status": "success", ...} on success
        if data.get('status') == 'success':
            logger.info('[SMS] ✓ Sent to %s — "%s..."', phone, message[:40])
            return True

        logger.warning('[SMS] Arkesel non-success for %s: %s', phone, data)
        return False

    except requests.exceptions.Timeout:
        logger.error('[SMS] Request timed out for %s', phone)
        return False
    except requests.exceptions.ConnectionError:
        logger.error('[SMS] Connection error — Arkesel unreachable')
        return False
    except requests.exceptions.HTTPError as exc:
        logger.error('[SMS] HTTP error for %s: %s', phone, exc)
        return False
    except (ValueError, KeyError) as exc:
        logger.error('[SMS] Unexpected Arkesel response format: %s', exc)
        return False


# ── ORDER SMS TEMPLATES ───────────────────────────────────
# One function per status — keeps signals.py thin and wording centralised.

def sms_order_confirmed(order):
    return send_sms(
        order.delivery_phone,
        f'Lynctel: Hi! Your order {order.order_ref} is confirmed. '
        f'Total: GHS {order.total_amount}. '
        f'We will text you when your rider is on the way.'
    )


def sms_order_dispatched(order):
    return send_sms(
        order.delivery_phone,
        f'Lynctel: Great news! Order {order.order_ref} is on its way. '
        f'Your rider will call {order.delivery_phone} on arrival.'
    )


def sms_order_delivered(order):
    return send_sms(
        order.delivery_phone,
        f'Lynctel: Order {order.order_ref} has been delivered. '
        f'Thank you for shopping with us! '
        f'Rate your experience at lynctel.up.railway.app'
    )


def sms_order_cancelled(order):
    return send_sms(
        order.delivery_phone,
        f'Lynctel: Your order {order.order_ref} has been cancelled. '
        f'Contact us on WhatsApp: +233558040216 if this was unexpected.'
    )


def sms_vendor_low_stock(vendor, products):
    """
    Sends a single low-stock alert to a vendor covering all their
    affected products. Called from order/signals.py after payment.
    """
    if not vendor.phone:
        return False

    names = ', '.join(
        f'{p.name} ({p.stock_qty} left)' for p in products
    )
    plural = 'products are' if len(products) > 1 else 'product is'

    return send_sms(
        vendor.phone,
        f'Lynctel Stock Alert: The following {plural} running low '
        f'in your shop: {names}. '
        f'Restock soon to avoid missed orders.'
    )
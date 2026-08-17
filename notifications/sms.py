"""
notifications/sms.py  —  Arkesel SMS gateway

No changes to core send_sms() — wiring only:
  UPGRADE: Added food order SMS templates to match the food system.
  UPGRADE: Added sms_food_order_* functions so food/views.py and
           food/signals.py can import from one place.
"""
import logging
import requests
from django.conf import settings

logger = logging.getLogger(__name__)
ARKESEL_URL = 'https://sms.arkesel.com/api/v2/sms/send'


def _normalise_phone(phone):
    if not phone:
        return None
    digits = ''.join(c for c in str(phone) if c.isdigit())
    if digits.startswith('233') and len(digits) == 12:
        return '0' + digits[3:]
    if digits.startswith('0') and len(digits) == 10:
        return digits
    return digits


def send_sms(to, message):
    """
    Send a single SMS via Arkesel v2.
    Returns True on success, False on any failure.
    Never raises — SMS failure must never break the caller.
    """
    api_key   = getattr(settings, 'ARKESEL_API_KEY',   None)
    sender_id = getattr(settings, 'ARKESEL_SENDER_ID', None)
    if not api_key:
        logger.warning('[SMS] ARKESEL_API_KEY not set')
        return False
    if not sender_id:
        logger.warning('[SMS] ARKESEL_SENDER_ID not set')
        return False
    phone = _normalise_phone(to)
    if not phone:
        logger.warning('[SMS] No valid phone: %r', to)
        return False
    try:
        resp = requests.post(
            ARKESEL_URL,
            json={'sender': sender_id, 'message': message, 'recipients': [phone]},
            headers={'api-key': api_key, 'Content-Type': 'application/json'},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get('status') == 'success':
            logger.info('[SMS] ✓ %s — %.40s…', phone, message)
            return True
        logger.warning('[SMS] Non-success: %s', data)
        return False
    except Exception as exc:
        logger.error('[SMS] Error sending to %s: %s', phone, exc)
        return False


# ── E-commerce order SMS ───────────────────────────────────────────────────────

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
        f'Rate us at lynctel.up.railway.app'
    )

def sms_order_cancelled(order):
    return send_sms(
        order.delivery_phone,
        f'Lynctel: Your order {order.order_ref} was cancelled. '
        f'WhatsApp us at +233558040216 if this was unexpected.'
    )

def sms_vendor_low_stock(vendor, products):
    if not vendor.phone:
        return False
    names  = ', '.join(f'{p.name} ({p.stock_qty} left)' for p in products)
    plural = 'products are' if len(products) > 1 else 'product is'
    return send_sms(
        vendor.phone,
        f'Lynctel Stock Alert: The following {plural} running low '
        f'in your shop: {names}. Restock soon to avoid missed orders.'
    )


# ── Food order SMS (NEW) ───────────────────────────────────────────────────────

def sms_food_order_confirmed(food_order):
    vendor_name = food_order.vendor.name if food_order.vendor else 'the restaurant'
    return send_sms(
        food_order.delivery_phone,
        f'Lynctel Food: {vendor_name} has confirmed your order '
        f'{food_order.order_ref}! '
        f'Estimated delivery: {food_order.estimated_delivery_time} mins. '
        f'Track: lynctel.up.railway.app/food/order/{food_order.order_ref}/'
    )

def sms_food_out_for_delivery(food_order):
    return send_sms(
        food_order.delivery_phone,
        f'Lynctel Food: Your order {food_order.order_ref} is on the way! '
        f'Your rider will call {food_order.delivery_phone} when nearby. '
        f'Track live: lynctel.up.railway.app/food/order/{food_order.order_ref}/'
    )

def sms_food_delivered(food_order):
    vendor_name = food_order.vendor.name if food_order.vendor else 'us'
    return send_sms(
        food_order.delivery_phone,
        f'Lynctel Food: Your food from {vendor_name} has arrived! '
        f'Enjoy your meal 🍽️ '
        f'Order again at lynctel.up.railway.app/food/'
    )

def sms_food_cancelled(food_order):
    return send_sms(
        food_order.delivery_phone,
        f'Lynctel Food: Sorry, your order {food_order.order_ref} was cancelled. '
        f'Contact us on WhatsApp: +233558040216'
    )

def sms_rider_assigned(food_order, rider_name=None):
    """SMS customer when a rider accepts their food order."""
    rider = rider_name or 'A rider'
    return send_sms(
        food_order.delivery_phone,
        f'Lynctel Food: {rider} is picking up your order from '
        f'{food_order.vendor.name if food_order.vendor else "the restaurant"}. '
        f'They will call you on arrival at {food_order.delivery_phone}.'
    )
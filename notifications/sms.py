"""
Termii SMS service wrapper.

Termii's API: https://developers.termii.com/messaging
Requires TERMII_API_KEY and TERMII_SENDER_ID in settings.py — both already
exist as unused config per the audit. This module is the missing piece
that actually calls the API.

Usage:
    from notifications.sms import send_sms
    send_sms(to='0558040216', message='Your order ORD-A1B2C3 has shipped!')

Design notes:
- Never raises on failure — a failed SMS should never break the request
  that triggered it (e.g. an order status update). Logs and returns False
  instead.
- Phone numbers are normalized to Termii's expected international format
  (233XXXXXXXXX, no '+', no leading 0) regardless of how they're stored
  locally (your User.phone field normalizes to "0XXXXXXXXX" per
  accounts/models.py's normalize_phone()).
"""
import logging

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

TERMII_BASE_URL = 'https://api.ng.termii.com/api/sms/send'


def _to_termii_format(phone):
    """
    Converts a Ghana phone number in any of these forms:
      0558040216 / 233558040216 / +233558040216
    into Termii's expected format: 233558040216
    """
    if not phone:
        return None
    digits = ''.join(c for c in phone if c.isdigit())
    if digits.startswith('233'):
        return digits
    if digits.startswith('0') and len(digits) == 10:
        return '233' + digits[1:]
    # Already looks international or malformed — pass through and let
    # Termii's API reject it explicitly rather than guessing further.
    return digits


def send_sms(to, message):
    """
    Sends a single SMS via Termii. Returns True on success, False on any
    failure (missing config, network error, non-2xx response). Never
    raises — callers (e.g. order status signals) should not have their
    own logic interrupted by an SMS failure.
    """
    api_key   = getattr(settings, 'TERMII_API_KEY', None)
    sender_id = getattr(settings, 'TERMII_SENDER_ID', None)

    if not api_key or not sender_id:
        logger.warning('[SMS] TERMII_API_KEY or TERMII_SENDER_ID not configured — skipping SMS.')
        return False

    phone = _to_termii_format(to)
    if not phone:
        logger.warning('[SMS] No valid phone number to send to: %r', to)
        return False

    payload = {
        'to':      phone,
        'from':    sender_id,
        'sms':     message,
        'type':    'plain',
        'channel': 'generic',
        'api_key': api_key,
    }

    try:
        response = requests.post(TERMII_BASE_URL, json=payload, timeout=10)
        response.raise_for_status()
        data = response.json()
        if data.get('code') == 'ok' or 'message_id' in data:
            logger.info('[SMS] Sent to %s: %s', phone, message[:50])
            return True
        logger.warning('[SMS] Termii returned non-ok response for %s: %s', phone, data)
        return False
    except requests.RequestException as exc:
        logger.error('[SMS] Failed to send to %s: %s', phone, exc)
        return False
    except (ValueError, KeyError) as exc:
        logger.error('[SMS] Unexpected Termii response format: %s', exc)
        return False


# ── ORDER-SPECIFIC MESSAGE TEMPLATES ───────────────────────
# Centralized here so wording stays consistent and signals.py stays thin.

def sms_order_confirmed(order):
    return send_sms(
        order.delivery_phone,
        f"Lynctel: Order {order.order_ref} confirmed! Total GHS {order.total_amount}. "
        f"We'll text you when it's on the way."
    )


def sms_order_dispatched(order):
    return send_sms(
        order.delivery_phone,
        f"Lynctel: Order {order.order_ref} is on its way! "
        f"A rider will call {order.delivery_phone} on arrival."
    )


def sms_order_delivered(order):
    return send_sms(
        order.delivery_phone,
        f"Lynctel: Order {order.order_ref} has been delivered. Thank you for shopping with us! 🎉"
    )


def sms_order_cancelled(order):
    return send_sms(
        order.delivery_phone,
        f"Lynctel: Order {order.order_ref} has been cancelled. "
        f"Contact support if this wasn't expected."
    )
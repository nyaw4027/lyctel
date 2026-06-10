"""
payment/paystack.py
Thin wrapper around the Paystack API.
"""
import hashlib, hmac, json, requests
from django.conf import settings


PAYSTACK_BASE = 'https://api.paystack.co'


def _headers():
    return {
        'Authorization': f'Bearer {settings.PAYSTACK_SECRET_KEY}',
        'Content-Type':  'application/json',
    }


def initialize_transaction(email: str, amount_ghs: float, reference: str,
                            callback_url: str, metadata: dict = None) -> dict:
    """
    Initialise a Paystack charge.
    amount_ghs  — amount in Ghana Cedis (we convert to pesewas × 100)
    Returns the Paystack response dict.
    """
    payload = {
        'email':        email,
        'amount':       int(round(amount_ghs * 100)),   # pesewas
        'currency':     'GHS',
        'reference':    reference,
        'callback_url': callback_url,
        'metadata':     metadata or {},
        'channels':     ['mobile_money', 'card', 'bank'],  # MoMo + card
    }
    r = requests.post(f'{PAYSTACK_BASE}/transaction/initialize',
                      headers=_headers(), json=payload, timeout=15)
    return r.json()


def verify_transaction(reference: str) -> dict:
    """Verify a completed transaction by reference."""
    r = requests.get(f'{PAYSTACK_BASE}/transaction/verify/{reference}',
                     headers=_headers(), timeout=15)
    return r.json()


def verify_webhook_signature(payload_bytes: bytes, signature: str) -> bool:
    """Validate the X-Paystack-Signature header on incoming webhooks."""
    secret = settings.PAYSTACK_SECRET_KEY.encode('utf-8')
    computed = hmac.new(secret, payload_bytes, hashlib.sha512).hexdigest()
    return hmac.compare_digest(computed, signature)
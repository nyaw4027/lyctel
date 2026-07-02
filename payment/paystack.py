
"""
payment/paystack.py
Thin wrapper around the Paystack API for Lynctel.
Handles transaction initialization, verification, and webhook validation.
"""
import hashlib
import hmac
import json

import requests as http_requests
from django.conf import settings

PAYSTACK_BASE = 'https://api.paystack.co'


def _headers():
    return {
        'Authorization': f'Bearer {settings.PAYSTACK_SECRET_KEY}',
        'Content-Type':  'application/json',
    }


def initialize_transaction(
    email: str,
    amount_ghs: float,
    reference: str,
    callback_url: str,
    metadata: dict = None,
    phone: str = None,
) -> dict:
    """
    Initialise a Paystack charge.
    amount_ghs  — amount in Ghana Cedis (converted to pesewas × 100 internally)
    phone       — optional, pre-fills the MoMo number field in Paystack popup
    Returns the full Paystack response dict.
    """
    meta = metadata or {}

    # Pre-fill phone number for MoMo if provided
    if phone:
        # Normalize to local format for Paystack MoMo pre-fill
        normalized = phone.strip()
        if normalized.startswith('+233'):
            normalized = '0' + normalized[4:]
        elif normalized.startswith('233'):
            normalized = '0' + normalized[3:]
        meta['phone'] = normalized

    payload = {
        'email':        email,
        'amount':       int(round(amount_ghs * 100)),  # pesewas
        'currency':     'GHS',
        'reference':    reference,
        'callback_url': callback_url,
        'metadata':     meta,
        # Ghana-specific channels — mobile_money covers MTN, Vodafone, AirtelTigo
        'channels':     ['mobile_money', 'card', 'bank_transfer'],
    }

    try:
        r = http_requests.post(
            f'{PAYSTACK_BASE}/transaction/initialize',
            headers=_headers(),
            json=payload,
            timeout=15,
        )
        return r.json()
    except Exception as e:
        return {'status': False, 'message': str(e)}


def verify_transaction(reference: str) -> dict:
    """
    Verify a completed transaction by its reference string.
    Returns the full Paystack response dict.
    Check data['status'] == 'success' and data['data']['amount'] for amount.
    """
    try:
        r = http_requests.get(
            f'{PAYSTACK_BASE}/transaction/verify/{reference}',
            headers=_headers(),
            timeout=15,
        )
        return r.json()
    except Exception as e:
        return {'status': False, 'message': str(e)}


def verify_webhook_signature(payload_bytes: bytes, signature: str) -> bool:
    """
    Validate the X-Paystack-Signature header on incoming webhook POSTs.
    Returns True if the signature matches, False otherwise.
    Always returns False (safe) if PAYSTACK_SECRET_KEY is not set.
    """
    secret_key = getattr(settings, 'PAYSTACK_SECRET_KEY', '')
    if not secret_key or not signature:
        return False

    try:
        secret   = secret_key.encode('utf-8')
        computed = hmac.new(secret, payload_bytes, hashlib.sha512).hexdigest()
        return hmac.compare_digest(computed, signature)
    except Exception:
        return False


def get_transaction(transaction_id: int) -> dict:
    """Fetch a transaction by its Paystack transaction ID (not reference)."""
    try:
        r = http_requests.get(
            f'{PAYSTACK_BASE}/transaction/{transaction_id}',
            headers=_headers(),
            timeout=15,
        )
        return r.json()
    except Exception as e:
        return {'status': False, 'message': str(e)}


def charge_momo(
    phone: str,
    amount_ghs: float,
    provider: str,
    email: str,
    reference: str,
) -> dict:
    """
    Directly charge a Mobile Money number (server-side, no popup).
    provider options for Ghana: 'mtn', 'vod' (Vodafone), 'tgo' (AirtelTigo)

    Use this for recurring charges or when you want to avoid the popup.
    For most cases, the popup via initialize_transaction is easier.
    """
    # Normalize to local format
    normalized = phone.strip()
    if normalized.startswith('+233'):
        normalized = '0' + normalized[4:]
    elif normalized.startswith('233'):
        normalized = '0' + normalized[3:]

    payload = {
        'email':     email,
        'amount':    int(round(amount_ghs * 100)),
        'currency':  'GHS',
        'reference': reference,
        'mobile_money': {
            'phone':    normalized,
            'provider': provider,
        },
    }

    try:
        r = http_requests.post(
            f'{PAYSTACK_BASE}/charge',
            headers=_headers(),
            json=payload,
            timeout=15,
        )
        return r.json()
    except Exception as e:
        return {'status': False, 'message': str(e)}
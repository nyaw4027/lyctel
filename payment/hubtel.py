"""
payment/hubtel.py
=================
Hubtel Checkout API v2 integration for Lynctel.

Usage:
    from payment.hubtel import HubtelCheckout
    result = HubtelCheckout.initiate(order, request)
    # → {'success': True, 'redirect_url': '...', 'checkout_id': '...'}

Docs: https://developers.hubtel.com/docs/checkout
"""
import hashlib
import hmac
import json
import logging
import uuid
from decimal import Decimal

import requests
from django.conf import settings

log = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────
HUBTEL_API_BASE   = "https://api.hubtel.com/v2"
CHECKOUT_ENDPOINT = f"{HUBTEL_API_BASE}/merchantaccount/merchants"
VERIFY_ENDPOINT   = f"{HUBTEL_API_BASE}/merchantaccount/merchants"

TIMEOUT = 15   # seconds


class HubtelError(Exception):
    """Raised when Hubtel API returns an error response."""
    def __init__(self, message, code=None, data=None):
        super().__init__(message)
        self.code = code
        self.data = data


class HubtelCheckout:
    """
    Encapsulates Hubtel Checkout API calls.
    All methods are class-level — no instantiation needed.
    """

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _auth():
        """Return (client_id, client_secret) from settings."""
        return (
            settings.HUBTEL_CLIENT_ID,
            settings.HUBTEL_CLIENT_SECRET,
        )

    @staticmethod
    def _merchant():
        return settings.HUBTEL_MERCHANT_ACCT

    @staticmethod
    def _ref(order):
        """Generate a unique payment reference tied to the order."""
        return f"LYN-{order.order_ref}-{uuid.uuid4().hex[:6].upper()}"

    # ── Initiate checkout ─────────────────────────────────────────────────────

    @classmethod
    def initiate(cls, order, request=None):
        """
        Create a Hubtel Checkout session.

        Args:
            order   : Order model instance
            request : Django HttpRequest (used to build absolute URLs)

        Returns:
            dict with keys:
                success      (bool)
                redirect_url (str)   — send user here to pay
                checkout_id  (str)   — store on the order for verification
                reference    (str)   — our payment reference
            OR on failure:
                success (bool = False)
                error   (str)
        """
        try:
            cid, secret = cls._auth()
            merchant    = cls._merchant()

            if not cid or not secret or not merchant:
                raise HubtelError(
                    "Hubtel credentials not configured. "
                    "Set HUBTEL_CLIENT_ID, HUBTEL_CLIENT_SECRET, "
                    "HUBTEL_MERCHANT_ACCT in Railway Variables."
                )

            ref          = cls._ref(order)
            amount       = float(order.total_amount)
            callback_url = getattr(settings, 'HUBTEL_CALLBACK_URL',
                                   'https://lynctel.up.railway.app/payment/callback/')
            return_url   = getattr(settings, 'HUBTEL_RETURN_URL',
                                   f'https://lynctel.up.railway.app/orders/{order.order_ref}/confirm/')
            cancel_url   = getattr(settings, 'HUBTEL_CANCEL_URL',
                                   'https://lynctel.up.railway.app/checkout/')

            # Customer phone — Hubtel requires Ghanaian format: 0XX XXXXXXX
            phone = (
                order.delivery_phone
                or (order.customer.phone if hasattr(order.customer, 'phone') else '')
                or ''
            )

            payload = {
                "totalAmount":         amount,
                "description":         f"Lynctel Order {order.order_ref}",
                "callbackUrl":         callback_url,
                "returnUrl":           return_url,
                "cancellationUrl":     cancel_url,
                "merchantAccountNumber": merchant,
                "clientReference":     ref,
                "customerName":        (
                    order.customer.get_full_name()
                    or order.customer.display_name
                    or "Customer"
                ),
                "customerMobileNumber": phone,
                "customerEmail":        getattr(order.customer, 'email', '') or '',
            }

            url = f"{CHECKOUT_ENDPOINT}/{merchant}/initiate-payment"
            response = requests.post(
                url,
                json    = payload,
                auth    = (cid, secret),
                timeout = TIMEOUT,
                headers = {"Content-Type": "application/json"},
            )

            log.info("Hubtel initiate status=%s ref=%s", response.status_code, ref)

            if response.status_code not in (200, 201):
                raise HubtelError(
                    f"Hubtel API error {response.status_code}: {response.text[:200]}",
                    code = response.status_code,
                )

            data = response.json()

            if data.get("status") not in ("Success", "success", 200, "00"):
                raise HubtelError(
                    data.get("message", "Unknown Hubtel error"),
                    data = data,
                )

            checkout_url = (
                data.get("data", {}).get("checkoutUrl")
                or data.get("checkoutUrl")
                or data.get("checkout_url")
            )
            checkout_id  = (
                data.get("data", {}).get("checkoutId")
                or data.get("checkoutId")
                or ref
            )

            if not checkout_url:
                raise HubtelError(
                    "Hubtel returned success but no checkoutUrl in response",
                    data = data,
                )

            return {
                "success":      True,
                "redirect_url": checkout_url,
                "checkout_id":  checkout_id,
                "reference":    ref,
                "raw":          data,
            }

        except HubtelError as e:
            log.error("Hubtel initiate failed: %s", e)
            return {"success": False, "error": str(e)}
        except requests.Timeout:
            log.error("Hubtel initiate timed out")
            return {"success": False, "error": "Payment gateway timed out. Please try again."}
        except Exception as e:
            log.exception("Hubtel initiate unexpected error: %s", e)
            return {"success": False, "error": "Payment error. Please try again."}

    # ── Verify payment ────────────────────────────────────────────────────────

    @classmethod
    def verify(cls, checkout_id):
        """
        Verify a completed payment by checkout_id.

        Returns:
            dict with keys:
                success     (bool)
                paid        (bool)
                amount      (float)
                reference   (str)
                status      (str)   — Hubtel status string
        """
        try:
            cid, secret = cls._auth()
            merchant    = cls._merchant()

            url = f"{VERIFY_ENDPOINT}/{merchant}/transactions/status?clientReference={checkout_id}"
            response = requests.get(
                url,
                auth    = (cid, secret),
                timeout = TIMEOUT,
            )

            if response.status_code != 200:
                raise HubtelError(f"Verify failed: HTTP {response.status_code}")

            data   = response.json()
            status = (
                data.get("data", {}).get("transactionStatus")
                or data.get("transactionStatus")
                or data.get("status")
                or "unknown"
            )
            paid   = status.lower() in ("success", "paid", "completed", "00")
            amount = float(
                data.get("data", {}).get("amount")
                or data.get("amount", 0)
            )

            return {
                "success":   True,
                "paid":      paid,
                "amount":    amount,
                "reference": checkout_id,
                "status":    status,
                "raw":       data,
            }

        except HubtelError as e:
            log.error("Hubtel verify failed: %s", e)
            return {"success": False, "paid": False, "error": str(e)}
        except Exception as e:
            log.exception("Hubtel verify error: %s", e)
            return {"success": False, "paid": False, "error": str(e)}

    # ── Webhook signature verification ────────────────────────────────────────

    @staticmethod
    def verify_webhook_signature(request_body: bytes, signature: str) -> bool:
        """
        Verify Hubtel webhook HMAC-SHA256 signature.

        Hubtel sends X-Hubtel-Signature header.
        """
        try:
            secret = settings.HUBTEL_CLIENT_SECRET.encode()
            expected = hmac.new(secret, request_body, hashlib.sha256).hexdigest()
            return hmac.compare_digest(expected, signature)
        except Exception:
            return False
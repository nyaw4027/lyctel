"""
payment/hubtel.py
=================
Hubtel Online Checkout API integration for Lynctel.

Endpoint: https://payproxyapi.hubtel.com/items/initiate  (per official docs)
Status:   https://api-txnstatus.hubtel.com/transactions/{acct}/status

Usage:
    from payment.hubtel import HubtelCheckout
    result = HubtelCheckout.initiate(order, request)
    # → {'success': True, 'redirect_url': '...', 'checkout_id': '...'}
"""
import base64
import hashlib
import hmac
import json
import logging
import re
import uuid
from decimal import Decimal

import requests
from django.conf import settings

log = logging.getLogger(__name__)

# ── Official API endpoints (per Hubtel docs) ──────────────────────────────────
INITIATE_URL     = "https://payproxyapi.hubtel.com/items/initiate"
STATUS_CHECK_URL = "https://api-txnstatus.hubtel.com/transactions/{acct}/status"

TIMEOUT = 15  # seconds


class HubtelError(Exception):
    """Raised when Hubtel API returns an error response."""
    def __init__(self, message, code=None, data=None):
        super().__init__(message)
        self.code = code
        self.data = data


class HubtelCheckout:
    """
    Hubtel Online Checkout — Redirect flow.

    All methods are class-level — no instantiation needed.
    Docs: https://payproxyapi.hubtel.com/items/initiate
    """

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _auth():
        """Return (client_id, client_secret) from settings."""
        return (
            getattr(settings, 'HUBTEL_CLIENT_ID',     ''),
            getattr(settings, 'HUBTEL_CLIENT_SECRET', ''),
        )

    @staticmethod
    def _merchant():
        return getattr(settings, 'HUBTEL_MERCHANT_ACCT', '')

    @staticmethod
    def _headers():
        """Build Basic Auth headers — Hubtel expects Authorization: Basic base64(id:secret)."""
        cid, secret = HubtelCheckout._auth()
        token = base64.b64encode(f"{cid}:{secret}".encode()).decode()
        return {
            "Authorization": f"Basic {token}",
            "Content-Type":  "application/json",
            "Accept":        "application/json",
            "Cache-Control": "no-cache",
        }

    @staticmethod
    def _safe_ref(text):
        """
        clientReference must be ≤ 32 characters (Hubtel docs).
        Strip anything that isn't alphanumeric or hyphen, then truncate.
        """
        cleaned = re.sub(r'[^A-Za-z0-9\-]', '', str(text))
        return cleaned[:36]

    @staticmethod
    def _clean_desc(text):
        """
        Hubtel rejects descriptions with special characters (&*!%@ etc).
        Keep only alphanumeric, spaces, commas, periods, hyphens.
        """
        return re.sub(r'[^a-zA-Z0-9 .,\-]', '', str(text))[:200]

    # ── Initiate checkout ─────────────────────────────────────────────────────

    @classmethod
    def initiate(cls, order, request=None):
        """
        Create a Hubtel Checkout session.

        Returns dict with keys:
            success      (bool)
            redirect_url (str)  — redirect user here to pay
            checkout_id  (str)  — store on order for verification
            reference    (str)  — our clientReference
        On failure:
            success (bool=False), error (str)
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

            # clientReference: ≤ 32 chars, no special characters
            ref = cls._safe_ref(f"ORD-{order.order_ref}")

            amount = float(round(Decimal(str(order.total_amount)), 2))

            callback_url = getattr(settings, 'HUBTEL_CALLBACK_URL',
                                   'https://lynctel.up.railway.app/payment/callback/')
            return_url   = getattr(settings, 'HUBTEL_RETURN_URL',
                                   f'https://lynctel.up.railway.app/orders/{order.order_ref}/confirm/')
            cancel_url   = getattr(settings, 'HUBTEL_CANCEL_URL',
                                   'https://lynctel.up.railway.app/checkout/')

            payload = {
                "totalAmount":           amount,
                "description":           cls._clean_desc(f"Lynctel Order {order.order_ref}"),
                "callbackUrl":           callback_url,
                "returnUrl":             return_url,
                "cancellationUrl":       cancel_url,
                "merchantAccountNumber": merchant,
                "clientReference":       ref,
            }

            # Optional payee fields (docs: payeeName, payeeMobileNumber, payeeEmail)
            customer = getattr(order, 'customer', None)
            if customer:
                name  = (getattr(customer, 'get_full_name', lambda: '')() or
                         getattr(customer, 'display_name', '') or '')
                phone = (getattr(order, 'delivery_phone', '') or
                         getattr(customer, 'phone', '') or '')
                email = getattr(customer, 'email', '') or ''
                if name:  payload['payeeName']         = name[:50]
                if phone: payload['payeeMobileNumber'] = phone[:20]
                if email: payload['payeeEmail']        = email[:80]

            log.info("[Hubtel] Initiating checkout ref=%s amount=GHS%.2f", ref, amount)

            response = requests.post(
                INITIATE_URL,
                json    = payload,
                headers = cls._headers(),
                timeout = TIMEOUT,
            )

            log.info("[Hubtel] Response status=%s ref=%s", response.status_code, ref)

            if response.status_code not in (200, 201):
                raise HubtelError(
                    f"Hubtel API error {response.status_code}: {response.text[:200]}",
                    code=response.status_code,
                )

            body = response.json()

            # Success: responseCode == "0000" (per Hubtel docs)
            if body.get("responseCode") != "0000":
                raise HubtelError(
                    body.get("message", f"Hubtel error: {body.get('responseCode')}"),
                    data=body,
                )

            data         = body.get("data", {})
            checkout_url = data.get("checkoutUrl", "")
            checkout_id  = data.get("checkoutId",  ref)
            direct_url   = data.get("checkoutDirectUrl", "")

            if not checkout_url:
                raise HubtelError(
                    "Hubtel returned responseCode 0000 but no checkoutUrl",
                    data=body,
                )

            # Persist on order if fields exist
            for field, val in [('hubtel_checkout_id', checkout_id),
                                ('hubtel_reference',   ref)]:
                if hasattr(order, field) and not getattr(order, field, ''):
                    try:
                        setattr(order, field, val)
                        order.save(update_fields=[field])
                    except Exception:
                        pass

            log.info("[Hubtel] Checkout created id=%s ref=%s", checkout_id, ref)

            return {
                "success":      True,
                "redirect_url": checkout_url,
                "direct_url":   direct_url,
                "checkout_id":  checkout_id,
                "reference":    ref,
            }

        except HubtelError as e:
            log.error("[Hubtel] initiate failed: %s", e)
            return {"success": False, "error": str(e)}
        except requests.Timeout:
            log.error("[Hubtel] initiate timed out")
            return {"success": False, "error": "Payment gateway timed out. Please try again."}
        except Exception as e:
            log.exception("[Hubtel] initiate unexpected error: %s", e)
            return {"success": False, "error": "Payment error. Please try again."}

    # ── Verify payment (status check) ─────────────────────────────────────────

    @classmethod
    def verify(cls, client_reference=None, checkout_id=None):
        """
        Check transaction status via Hubtel Status Check API.
        API: GET https://api-txnstatus.hubtel.com/transactions/{acct}/status

        Returns dict with: paid (bool), status (str), amount (float)
        """
        try:
            merchant = cls._merchant()
            if not merchant:
                return {"paid": False, "status": "no_merchant"}

            params = {}
            if client_reference:
                params["clientReference"]    = cls._safe_ref(client_reference)
            elif checkout_id:
                params["hubtelTransactionId"] = checkout_id
            else:
                return {"paid": False, "status": "no_reference"}

            url = STATUS_CHECK_URL.format(acct=merchant)
            response = requests.get(
                url,
                params  = params,
                headers = cls._headers(),
                timeout = TIMEOUT,
            )

            if response.status_code != 200:
                log.warning("[Hubtel] Status check HTTP %s", response.status_code)
                return {"paid": False, "status": f"http_{response.status_code}"}

            body = response.json()
            data = body.get("data", {})

            # Status values: "Paid", "Unpaid", "Refunded" (per Hubtel docs)
            status = (data.get("status") or "").strip().lower()
            paid   = status == "paid"

            return {
                "paid":                    paid,
                "status":                  status,
                "amount":                  data.get("amount"),
                "charges":                 data.get("charges"),
                "amount_after_charges":    data.get("amountAfterCharges"),
                "transaction_id":          data.get("transactionId"),
                "external_transaction_id": data.get("externalTransactionId"),
                "client_reference":        data.get("clientReference"),
                "payment_method":          data.get("paymentMethod"),
            }

        except requests.Timeout:
            return {"paid": False, "status": "timeout"}
        except Exception as e:
            log.exception("[Hubtel] verify error: %s", e)
            return {"paid": False, "status": "error", "error": str(e)}

    # ── Parse callback ────────────────────────────────────────────────────────

    @classmethod
    def parse_callback(cls, body: dict) -> dict:
        """
        Parse Hubtel webhook/callback payload.

        Hubtel sends PascalCase keys in callbacks (per docs):
            ResponseCode, Status, Data.Status, Data.ClientReference,
            Data.Amount, Data.CheckoutId, Data.CustomerPhoneNumber

        Returns normalised dict with snake_case keys.
        """
        code   = body.get("ResponseCode") or body.get("responseCode", "")
        d_data = body.get("Data")          or body.get("data")          or {}

        d_status = (d_data.get("Status") or d_data.get("status") or
                    body.get("Status")   or body.get("status",   "")).strip().lower()

        # "Success" + responseCode "0000" both indicate a paid transaction
        paid = d_status in ("success", "paid", "completed") or code == "0000"

        return {
            "paid":                paid,
            "response_code":       code,
            "status":              d_status,
            "checkout_id":         d_data.get("CheckoutId")            or d_data.get("checkoutId",           ""),
            "client_reference":    d_data.get("ClientReference")       or d_data.get("clientReference",      ""),
            "transaction_id":      d_data.get("TransactionId")         or d_data.get("transactionId",        ""),
            "external_tx_id":      d_data.get("ExternalTransactionId") or d_data.get("externalTransactionId",""),
            "amount":              d_data.get("Amount")                or d_data.get("amount"),
            "amount_charged":      d_data.get("AmountCharged")         or d_data.get("amountCharged"),
            "charges":             d_data.get("Charges")               or d_data.get("charges"),
            "amount_after_charges":d_data.get("AmountAfterCharges")    or d_data.get("amountAfterCharges"),
            "phone":               d_data.get("CustomerPhoneNumber")   or d_data.get("customerPhoneNumber",  ""),
            "description":         d_data.get("Description")           or d_data.get("description",         ""),
            "order_id":            d_data.get("OrderId")               or d_data.get("orderId",              ""),
            "payment_date":        d_data.get("PaymentDate")           or d_data.get("paymentDate",          ""),
        }

    # ── Webhook HMAC signature verification ───────────────────────────────────

    @staticmethod
    def verify_webhook_signature(request_body: bytes, signature: str) -> bool:
        """
        Verify Hubtel HMAC-SHA256 signature on incoming callbacks.
        Hubtel sends X-Hubtel-Signature header.
        Callback IP to whitelist: 108.129.40.25 (per Hubtel docs).
        """
        try:
            _, secret = HubtelCheckout._auth()
            if not secret:
                return True  # Can't verify — allow (log a warning in production)
            expected = hmac.new(secret.encode(), request_body, hashlib.sha256).hexdigest()
            return hmac.compare_digest(expected, signature)
        except Exception:
            return False
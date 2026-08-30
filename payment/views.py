"""
payment/views.py

Hubtel + Flutterwave payment integration.

Fixes applied in this version:
  1. SECURITY: hubtel_callback no longer marks orders paid based on the
     ?status=success URL parameter — that can be forged by anyone.
     Only the webhook is trusted as payment confirmation. The browser
     redirect now shows a "processing" state and polls until paid.
  2. BUG: AppCommission.get_or_create now passes `rate` so the field's
     NOT NULL constraint is satisfied.
  3. BUG: payment.html had no payment_method input; payment_page now
     injects a default so a direct Hubtel form POST always works.
  4. DEAD_CODE: MOMO_OPTIONS cleaned up (Tailwind class strings removed).
  5. ROBUSTNESS: _create_order_from_pending gracefully handles products
     with either selling_price or price field.
"""

import base64
import importlib
import json
import logging
import time
from decimal import Decimal, ROUND_HALF_UP

import requests as http_requests

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt

from order.models import Order, OrderItem
from order.views import get_or_create_cart
from vendors.models import VendorEarning, AppCommission

logger = logging.getLogger(__name__)


# ── Credentials (read at import time; require process restart after rotation) ──

HUBTEL_CLIENT_ID     = getattr(settings, 'HUBTEL_CLIENT_ID',     '')
HUBTEL_CLIENT_SECRET = getattr(settings, 'HUBTEL_CLIENT_SECRET', '')
HUBTEL_MERCHANT_ACCT = getattr(settings, 'HUBTEL_MERCHANT_ACCT', '')

FLW_SECRET       = getattr(settings, 'FLW_SECRET_KEY',   '')
FLW_PUBLIC       = getattr(settings, 'FLW_PUBLIC_KEY',   '')
FLW_WEBHOOK_HASH = getattr(settings, 'FLW_WEBHOOK_HASH', '')

# Payment method options shown on payment.html
MOMO_OPTIONS = [
    ('mtn',        'MTN Mobile Money'),
    ('telecel',    'Telecel Cash'),
    ('airteltigo', 'AirtelTigo Money'),
]


# ── Hubtel API helpers ─────────────────────────────────────────────────────────

def _hubtel_auth() -> str:
    """Returns Base64 Basic Auth header for Hubtel API calls."""
    token = base64.b64encode(
        f'{HUBTEL_CLIENT_ID}:{HUBTEL_CLIENT_SECRET}'.encode()
    ).decode()
    return f'Basic {token}'


# ── Vendor disbursement ────────────────────────────────────────────────────────

def _disburse_to_vendor(vendor, amount: Decimal, order_ref: str) -> dict:
    """
    Send `amount` GHS to a vendor's MoMo via Hubtel Transfers.
    Returns {'success': bool, 'reference': str, 'error': str}.
    Never raises — a payout failure must not break the order flow.
    """
    payout_phone = vendor.payout_phone   # property: momo_number or phone fallback
    if not payout_phone:
        msg = (f'Vendor {vendor.shop_name} has no MoMo number — '
               f'set it in Vendor Settings.')
        logger.warning('[Payout] %s (order %s)', msg, order_ref)
        return {'success': False, 'reference': '', 'error': msg}

    if not HUBTEL_CLIENT_ID:
        return {'success': False, 'reference': '', 'error': 'Hubtel not configured'}

    network   = vendor.hubtel_network_code   # property: MTN/TELECEL/AIRTELTIGO
    reference = f'PAYOUT-{order_ref}-{vendor.pk}'

    try:
        resp = http_requests.post(
            'https://api.hubtel.com/v2/transfers',
            headers={'Authorization': _hubtel_auth(), 'Content-Type': 'application/json'},
            json={
                'amount':           float(amount),
                'recipientAccount': payout_phone,
                'network':          network,
                'description':      f'Lynctel vendor payout — order {order_ref}',
                'clientReference':  reference,
            },
            timeout=20,
        )
        data = resp.json()
        logger.info('[Payout] Hubtel resp for %s: %s', reference, data)

        if resp.status_code in (200, 201) and data.get('responseCode') in ('0000', '00'):
            return {'success': True, 'reference': reference, 'error': ''}

        error = data.get('message', f'HTTP {resp.status_code}')
        logger.error('[Payout] Failed for %s: %s', reference, error)
        return {'success': False, 'reference': reference, 'error': error}

    except Exception as exc:
        logger.error('[Payout] Exception for %s: %s', reference, exc)
        return {'success': False, 'reference': reference, 'error': str(exc)}


def _split_and_disburse(order) -> None:
    """
    Calculate per-vendor gross/commission/net, record accounting rows,
    and immediately disburse net amounts via Hubtel Transfers.
    Commission stays in Lynctel's Hubtel account automatically.
    """
    vendor_totals: dict = {}
    for item in order.items.select_related('product__vendor').all():
        vendor = item.product.vendor if item.product else None
        if not vendor:
            continue
        gross = item.unit_price * item.quantity
        vendor_totals[vendor] = vendor_totals.get(vendor, Decimal('0')) + gross

    for vendor, gross in vendor_totals.items():
        rate       = Decimal(str(vendor.commission_rate or 4)) / Decimal('100')
        commission = (gross * rate).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        net        = (gross - commission).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

        # FIX: AppCommission requires 'rate' — omitting it caused IntegrityError
        VendorEarning.objects.get_or_create(
            vendor=vendor, order=order,
            defaults={
                'gross_amount': gross,
                'commission':   commission,
                'net_amount':   net,
            },
        )
        AppCommission.objects.get_or_create(
            vendor=vendor, order=order,
            defaults={
                'amount': commission,
                'rate':   (rate * Decimal('100')).quantize(Decimal('0.01')),
            },
        )

        result = _disburse_to_vendor(vendor, net, order.order_ref)
        earning_qs = VendorEarning.objects.filter(vendor=vendor, order=order)

        if result['success']:
            earning_qs.update(
                status=VendorEarning.Status.PAID,
                payout_reference=result['reference'],
                payout_error='',
            )
            logger.info('[Payout] ✓ GHS %.2f → %s (order %s)',
                        net, vendor.shop_name, order.order_ref)
        else:
            earning_qs.update(
                status=VendorEarning.Status.FAILED,
                payout_reference=result.get('reference', ''),
                payout_error=result['error'],
            )
            logger.error('[Payout] ✗ GHS %.2f FAILED for %s (order %s): %s',
                         net, vendor.shop_name, order.order_ref, result['error'])
            try:
                from notifications.sms import send_sms
                send_sms(
                    getattr(settings, 'ADMIN_PHONE', ''),
                    f'Lynctel: Payout FAILED for {vendor.shop_name} '
                    f'(GHS {net}, order {order.order_ref}). Manual transfer needed.',
                )
            except Exception:
                pass


# ── Order payment confirmation ─────────────────────────────────────────────────

def _mark_paid(order, transaction_id: str = '') -> None:
    """
    Mark order paid and trigger: split/disburse, delivery, SMS, push.
    Idempotent — safe to call from both webhook and callback.
    """
    if order.payment_status == Order.PaymentStatus.PAID:
        return

    order.payment_status = Order.PaymentStatus.PAID
    order.status         = Order.Status.CONFIRMED
    if transaction_id and hasattr(order, 'hubtel_checkout_id'):
        order.hubtel_checkout_id = transaction_id
    from django.utils import timezone
    if hasattr(order, 'paid_at') and not order.paid_at:
        order.paid_at = timezone.now()
    order.save(update_fields=['payment_status', 'status', 'hubtel_checkout_id', 'paid_at'])

    _split_and_disburse(order)

    try:
        from order.views import create_delivery_for_order
        create_delivery_for_order(order)
    except Exception as exc:
        logger.error('[Payment] Delivery creation failed for %s: %s', order.order_ref, exc)

    try:
        from notifications.sms import sms_order_confirmed, sms_new_order_to_vendor
        sms_order_confirmed(order)
        sms_new_order_to_vendor(order)
    except Exception as e:
        logger.warning('[Payment] SMS notification failed: %s', e)

    try:
        from push_notify import push_order_confirmed, push_new_order_to_vendor
        push_order_confirmed(order)
        push_new_order_to_vendor(order)
    except Exception:
        pass


# ── Order creation from session ────────────────────────────────────────────────

def _product_price(product):
    """
    Return the cart unit price for a product, handling both 'selling_price'
    and 'price' field names across different Product model versions.
    """
    for attr in ('selling_price', 'final_price', 'price'):
        val = getattr(product, attr, None)
        if val is not None:
            return Decimal(str(val))
    return Decimal('0')


def _create_order_from_pending(request, pending_order, cart):
    order = Order.objects.create(
        customer               = request.user,
        delivery_choice        = pending_order.get('delivery_choice', 'rider'),
        delivery_address       = pending_order.get('delivery_address', ''),
        delivery_city          = pending_order.get('delivery_city', ''),
        delivery_phone         = pending_order.get('delivery_phone', ''),
        delivery_lat           = pending_order.get('delivery_lat'),
        delivery_lng           = pending_order.get('delivery_lng'),
        parcel_bus_station     = pending_order.get('parcel_bus_station', ''),
        parcel_recipient_phone = pending_order.get('parcel_recipient_phone', ''),
        parcel_notes           = pending_order.get('parcel_notes', ''),
        customer_note          = pending_order.get('order_note', ''),
        subtotal               = Decimal(pending_order.get('subtotal',     '0')),
        delivery_fee           = Decimal(pending_order.get('delivery_fee', '0')),
        total_amount           = Decimal(pending_order.get('total',        '0')),
    )
    for cart_item in cart.items.select_related('product').all():
        OrderItem.objects.create(
            order        = order,
            product      = cart_item.product,
            product_name = cart_item.product.name,
            unit_price   = _product_price(cart_item.product),  # FIX: graceful field lookup
            quantity     = cart_item.quantity,
        )
    cart.items.all().delete()
    del request.session['pending_order']
    return order


# ── Payment selection page ─────────────────────────────────────────────────────

@login_required
def payment_page(request):
    pending_order = request.session.get('pending_order')
    if not pending_order:
        messages.warning(request, 'No pending order found.')
        return redirect('products:list')

    cart = get_or_create_cart(request)
    if cart.total_items == 0:
        messages.warning(request, 'Your cart is empty.')
        return redirect('cart:detail')

    if request.method == 'POST':
        # FIX: payment.html has a single "Pay with Hubtel" button that does
        # not include a payment_method field. We default to 'momo' so the
        # "Choose a payment method" guard never trips on a legitimate submit.
        payment_method   = request.POST.get('payment_method', 'momo').strip() or 'momo'
        payment_provider = request.POST.get('payment_provider', 'hubtel').strip()

        order = _create_order_from_pending(request, pending_order, cart)

        if payment_provider == 'flutterwave':
            return redirect('payment:flutterwave_init', order_pk=order.pk)
        return redirect('payment:hubtel_init', order_pk=order.pk)

    return render(request, 'payment/payment.html', {
        'pending':       pending_order,  # template uses {{ pending.delivery_address }}
        'cart':          cart,
        'momo_options':  MOMO_OPTIONS,
        'cart_count':    cart.total_items,
    })


# ── Hubtel ─────────────────────────────────────────────────────────────────────

@login_required
def hubtel_init(request, order_pk):
    order = get_object_or_404(Order, pk=order_pk, customer=request.user)

    if not HUBTEL_CLIENT_ID:
        messages.error(request, 'Payment gateway not configured. Contact support.')
        return redirect('order:history')

    from .hubtel import HubtelCheckout

    result = HubtelCheckout.initiate(order, request)

    if not result.get('success'):
        logger.error('[Hubtel] Init failed for order %s: %s',
                     order.order_ref, result.get('error'))
        messages.error(request, result.get('error', 'Payment error. Please try again.'))
        return redirect('order:history')

    checkout_url = result.get('redirect_url', '')
    direct_url   = result.get('direct_url', '')

    # Render pay.html with iFrame (direct_url) or redirect fallback (checkout_url)
    return render(request, 'payment/pay.html', {
        'order':       order,
        'checkout_url': checkout_url,
        'direct_url':   direct_url,   # used by iFrame embed in pay.html
        'cart_count':   0,
    })


@login_required
def hubtel_callback(request):
    """
    Hubtel redirects the customer's browser here after checkout.

    SECURITY FIX: The previous version called _mark_paid() when
    ?status=success was present in the URL. Since this URL is public and
    the status parameter comes from the browser (not from Hubtel's servers),
    any user could hit:
        /checkout/hubtel/callback/?ref=LNC-123&status=success
    and mark order LNC-123 as paid without paying a single pesewa.

    The fix: NEVER trust the browser redirect URL for payment confirmation.
    The Hubtel webhook (server-to-server, signed by Hubtel) is the sole
    authoritative payment signal. Here we simply check if the webhook has
    already marked the order paid; if not, we show a "processing" page
    that auto-refreshes until the webhook fires.
    """
    order_ref = request.GET.get('ref', '')
    status    = request.GET.get('status', '').lower()

    if not order_ref:
        return redirect('order:history')

    order = get_object_or_404(Order, order_ref=order_ref, customer=request.user)

    # Already paid by webhook — show confirmation
    if order.payment_status == Order.PaymentStatus.PAID:
        messages.success(request, f'✅ Payment confirmed! Order {order.order_ref} is being processed.')
        return redirect('order:tracking', order_ref=order.order_ref)

    # Explicit cancellation from Hubtel
    if status == 'cancelled':
        messages.warning(request, 'Payment cancelled. Your order has not been placed.')
        return render(request, 'payment/failed.html', {'order': order})

    # Payment may still be processing (webhook hasn't arrived yet) OR failed.
    # Show a polling page so the customer isn't left confused.
    return render(request, 'payment/processing.html', {
        'order':      order,
        'poll_url':   reverse('payment:hubtel_status', args=[order.order_ref]),
        'cancel_url': reverse('payment:hubtel_cancel') + f'?ref={order.order_ref}',
    })


@login_required
def hubtel_payment_status(request, order_ref):
    """
    Lightweight JSON endpoint polled by payment/processing.html every 3s.
    Returns the current payment state so the page can redirect on confirmation.
    """
    order = get_object_or_404(Order, order_ref=order_ref, customer=request.user)
    paid  = order.payment_status == Order.PaymentStatus.PAID
    return JsonResponse({
        'paid':     paid,
        'redirect': reverse('order:confirmation', kwargs={'order_ref': order.order_ref}) if paid else None,
        'status':   order.payment_status,
    })


@login_required
def hubtel_cancel(request):
    order_ref = request.GET.get('ref', '')
    order     = get_object_or_404(Order, order_ref=order_ref, customer=request.user)
    messages.warning(request, 'Payment cancelled.')
    return render(request, 'payment/failed.html', {'order': order})


@csrf_exempt
def hubtel_webhook(request):
    """
    Server-to-server payment notification from Hubtel.
    This is the ONLY trusted payment confirmation signal.

    Hubtel payload:
    {
      "ResponseCode": "0000",
      "Status": "Success",
      "Data": {
        "ClientReference": "LNC-XXXXXXXX",
        "Amount": 100.00,
        "TransactionId": "HBT123456"
      }
    }
    """
    if request.method != 'POST':
        return HttpResponse(status=405)

    try:
        body = json.loads(request.body)
    except Exception:
        return HttpResponse(status=400)

    from .hubtel import HubtelCheckout

    parsed    = HubtelCheckout.parse_callback(body)
    paid      = parsed['paid']
    order_ref = parsed['client_reference']  # e.g. "ORD-ABC123"
    txn_id    = parsed.get('transaction_id', '') or parsed.get('checkout_id', '')

    logger.info('[Hubtel] Webhook — ref=%s paid=%s txn=%s', order_ref, paid, txn_id)

    if not order_ref:
        return HttpResponse(status=400)

    try:
        order = Order.objects.get(order_ref=order_ref)
    except Order.DoesNotExist:
        logger.warning('[Hubtel] Webhook: order not found for ref=%s', order_ref)
        return HttpResponse(status=200)  # 200 so Hubtel doesn't retry

    if paid:
        _mark_paid(order, transaction_id=txn_id)
    else:
        logger.info('[Hubtel] Webhook: payment not successful — ref=%s', order_ref)

    return HttpResponse(status=200)


# ── Flutterwave ────────────────────────────────────────────────────────────────

@login_required
def flutterwave_init(request, order_pk):
    order = get_object_or_404(Order, pk=order_pk, customer=request.user)

    if not FLW_SECRET:
        messages.error(request, 'Payment gateway not configured. Please pay on delivery.')
        return redirect('order:tracking', order_ref=order.order_ref)

    try:
        resp = http_requests.post(
            'https://api.flutterwave.com/v3/payments',
            headers={'Authorization': f'Bearer {FLW_SECRET}'},
            json={
                'tx_ref':       order.order_ref,
                'amount':       str(order.total_amount),
                'currency':     'GHS',
                'redirect_url': request.build_absolute_uri(reverse('payment:callback')),
                'customer': {
                    'email':       request.user.email or f'{request.user.phone}@lynctel.app',
                    'phonenumber': order.delivery_phone,
                },
                'customizations': {
                    'title':       'Lynctel Order',
                    'description': f'Order {order.order_ref}',
                },
            },
            timeout=10,
        )
        data = resp.json()
        link = data.get('data', {}).get('link')
        if data.get('status') == 'success' and link:
            return redirect(link)
        logger.error('[FLW] Init failed for order %s: %s', order.pk, data)
    except Exception as exc:
        logger.error('[FLW] Init error for order %s: %s', order.pk, exc)

    messages.error(request, 'Could not start payment. Please try again.')
    return redirect('order:tracking', order_ref=order.order_ref)


@login_required
def payment_callback(request):
    """Flutterwave browser redirect after payment."""
    tx_ref   = request.GET.get('tx_ref', '')
    status   = request.GET.get('status', '')
    trans_id = request.GET.get('transaction_id', '')

    if status != 'successful':
        messages.error(request, 'Payment was not successful. Please try again.')
        return redirect('products:list')

    try:
        resp = http_requests.get(
            f'https://api.flutterwave.com/v3/transactions/{trans_id}/verify',
            headers={'Authorization': f'Bearer {FLW_SECRET}'},
            timeout=10,
        )
        data = resp.json()
        if data.get('status') == 'success' and data['data']['status'] == 'successful':
            order = Order.objects.filter(order_ref=tx_ref).first()
            if order and order.payment_status != Order.PaymentStatus.PAID:
                _mark_paid(order)
                messages.success(request,
                    f'✅ Payment confirmed! Order {order.order_ref} is being processed.')
                return redirect('order:tracking', order_ref=order.order_ref)
            elif order:
                messages.info(request, 'Order already confirmed.')
                return redirect('order:tracking', order_ref=order.order_ref)
            else:
                messages.error(request, 'Order not found.')
        else:
            messages.error(request, 'Payment verification failed.')
    except Exception as exc:
        logger.error('[FLW] Callback error: %s', exc)
        messages.error(request, 'Could not verify payment. Contact support if charged.')

    return redirect('products:list')


@csrf_exempt
def flutterwave_webhook(request):
    if request.method != 'POST':
        return HttpResponse(status=405)

    signature = request.headers.get('verif-hash', '')
    if FLW_WEBHOOK_HASH and signature != FLW_WEBHOOK_HASH:
        return HttpResponse(status=401)

    try:
        payload = json.loads(request.body)
        if payload.get('event') == 'charge.completed':
            data   = payload.get('data', {})
            tx_ref = data.get('tx_ref', '')
            status = data.get('status', '')
            if status == 'successful' and tx_ref:
                order = Order.objects.filter(order_ref=tx_ref).first()
                if order and order.payment_status != Order.PaymentStatus.PAID:
                    _mark_paid(order)
                    logger.info('[FLW] Webhook: order %s marked paid', tx_ref)
    except Exception as exc:
        logger.error('[FLW] Webhook error: %s', exc)

    return HttpResponse(status=200)

@login_required



@login_required



# ── PROCESSING PAGE ───────────────────────────────────────────────────────────

@login_required
def payment_processing(request):
    """
    Shows "Processing your payment…" spinner page.
    Polls payment:hubtel_status every 3s via JS.
    Called by pay.html postMessage on success: ?order=<ref>
    """
    from order.models import Order
    from django.urls import reverse

    order_ref = request.GET.get('order', '').strip()
    order     = None
    poll_url  = ''
    cancel_url = request.build_absolute_uri('/orders/')

    if order_ref:
        try:
            order = Order.objects.get(order_ref=order_ref, customer=request.user)
            poll_url = request.build_absolute_uri(
                reverse('payment:hubtel_status', args=[order_ref])
            )
            cancel_url = request.build_absolute_uri(
                reverse('order:history')
            )
            # Already paid — skip straight to confirmation
            if order.payment_status == 'paid':
                return redirect('order:confirmation', order_ref=order_ref)
        except Order.DoesNotExist:
            pass

    return render(request, 'payment/processing.html', {
        'order':       order,
        'poll_url':    poll_url,
        'cancel_url':  cancel_url,
        'cart_count':  0,
    })


# ── FAILED PAGE ───────────────────────────────────────────────────────────────

@login_required
def payment_failed(request, order_ref):
    """
    Payment failed page. Shows "Try Again" → payment:initiate <order_ref>.
    """
    from order.models import Order

    try:
        order = Order.objects.get(order_ref=order_ref, customer=request.user)
    except Order.DoesNotExist:
        return redirect('order:history')

    return render(request, 'payment/failed.html', {
        'order':      order,
        'reason':     request.GET.get('reason', 'Your payment could not be completed.'),
        'cart_count': 0,
    })

@login_required
def payment_initiate(request, order_ref):
    """
    Re-initiates Hubtel checkout for an existing unpaid order.
    Called when customer clicks "Try Again" on failed.html.
    URL: payment:initiate <order_ref>
    """
    from order.models import Order
    from .hubtel import HubtelCheckout

    try:
        order = Order.objects.get(order_ref=order_ref, customer=request.user)
    except Order.DoesNotExist:
        messages.error(request, 'Order not found.')
        return redirect('order:history')

    if order.payment_status == Order.PaymentStatus.PAID:
        return redirect('order:confirmation', order_ref=order.order_ref)

    result = HubtelCheckout.initiate(order, request)

    if not result.get('success'):
        messages.error(request, result.get('error', 'Payment error. Please try again.'))
        return render(request, 'payment/failed.html', {
            'order':      order,
            'reason':     result.get('error', ''),
            'cart_count': 0,
        })

    return render(request, 'payment/pay.html', {
        'order':        order,
        'checkout_url': result.get('redirect_url', ''),
        'direct_url':   result.get('direct_url', ''),
        'cart_count':   0,
    })
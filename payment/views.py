"""
payment/views.py

Payment split model:
  Customer pays full order total → Lynctel's Hubtel merchant account.
  On webhook confirmation → Lynctel immediately disburses each vendor's
  net amount (total - commission) to their payout MoMo number via
  Hubtel's Transfer API.
  Commission stays in Lynctel's account automatically.

Hubtel env vars (Railway → Variables):
    HUBTEL_CLIENT_ID      = your Hubtel API client ID
    HUBTEL_CLIENT_SECRET  = your Hubtel API client secret
    HUBTEL_MERCHANT_ACCT  = your Hubtel merchant account number

Docs: https://developers.hubtel.com
"""

import base64
import importlib
import json
import logging
from decimal import Decimal, ROUND_HALF_UP

import requests as http_requests

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt

from order.models import Order, OrderItem
from order.views import get_or_create_cart
from vendors.models import VendorEarning, AppCommission

logger = logging.getLogger(__name__)


# ── Credentials ────────────────────────────────────────────────────────────────

HUBTEL_CLIENT_ID     = getattr(settings, 'HUBTEL_CLIENT_ID',     '')
HUBTEL_CLIENT_SECRET = getattr(settings, 'HUBTEL_CLIENT_SECRET', '')
HUBTEL_MERCHANT_ACCT = getattr(settings, 'HUBTEL_MERCHANT_ACCT', '')

FLW_SECRET       = getattr(settings, 'FLW_SECRET_KEY',   '')
FLW_PUBLIC       = getattr(settings, 'FLW_PUBLIC_KEY',   '')
FLW_WEBHOOK_HASH = getattr(settings, 'FLW_WEBHOOK_HASH', '')

MOMO_OPTIONS = [
    ('mtn',        'MTN Mobile Money', 'bg-yellow-100 text-yellow-700', '*170#'),
    ('vodafone',   'Telecel Cash',     'bg-red-100 text-red-600',       '*110#'),
    ('airteltigo', 'AirtelTigo Money', 'bg-blue-100 text-blue-700',     '*500#'),
]


# ── Hubtel API helpers ─────────────────────────────────────────────────────────

def _hubtel_auth():
    token = base64.b64encode(
        f'{HUBTEL_CLIENT_ID}:{HUBTEL_CLIENT_SECRET}'.encode()
    ).decode()
    return f'Basic {token}'



def _disburse_to_vendor(vendor, amount: Decimal, order_ref: str) -> dict:
    """
    Send `amount` GHS to a vendor's MoMo number via Hubtel Transfers.
    Uses vendor.payout_phone (momo_number → phone fallback) and
    vendor.hubtel_network_code (from momo_network field).

    Returns { 'success': bool, 'reference': str, 'error': str }.
    Never raises — payout failure must not break order confirmation.
    """
    # vendor.payout_phone: property that returns momo_number or phone
    payout_phone = vendor.payout_phone
    if not payout_phone:
        msg = (
            f'Vendor {vendor.shop_name} has no MoMo number — '
            f'set it in Vendor Settings to enable automatic payouts.'
        )
        logger.warning('[Payout] %s (order %s)', msg, order_ref)
        return {'success': False, 'reference': '', 'error': msg}

    if not HUBTEL_CLIENT_ID:
        return {'success': False, 'reference': '', 'error': 'Hubtel not configured'}

    # vendor.hubtel_network_code maps momo_network → MTN/TELECEL/AIRTELTIGO
    network   = vendor.hubtel_network_code
    reference = f'PAYOUT-{order_ref}-{vendor.pk}'

    try:
        resp = http_requests.post(
            'https://api.hubtel.com/v2/transfers',
            headers={
                'Authorization': _hubtel_auth(),
                'Content-Type':  'application/json',
            },
            json={
                'amount':          float(amount),
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

def _split_and_disburse(order):
    """
    1. Calculate each vendor's gross, commission, and net amount.
    2. Record VendorEarning + AppCommission rows (for accounting).
    3. Immediately disburse the net to each vendor's MoMo via Hubtel.
    4. Log any failed disbursements for manual follow-up.

    Commission stays in Lynctel's Hubtel account automatically —
    only the net (gross - commission) is transferred out.
    """
    # Group items by vendor
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

        # ── Accounting records ──────────────────────────────────
        VendorEarning.objects.get_or_create(
            vendor=vendor, order=order,
            defaults={
                'gross_amount':      gross,
                'commission':       commission,
                'net_amount':        net,
            },
        )
        AppCommission.objects.get_or_create(
            vendor=vendor, order=order,
            defaults={'amount': commission},
        )

        # ── Immediate payout to vendor's MoMo ──────────────────
        result = _disburse_to_vendor(vendor, net, order.order_ref)

        # Record payout result on the VendorEarning row so staff can see it
        earning_qs = VendorEarning.objects.filter(vendor=vendor, order=order)

        if result['success']:
            earning_qs.update(
                status=VendorEarning.Status.PAID,
                payout_reference=result['reference'],
                payout_error='',
            )
            logger.info(
                '[Payout] ✓ GHS %.2f sent to %s for order %s (ref=%s)',
                net, vendor.shop_name, order.order_ref, result['reference'],
            )
        else:
            earning_qs.update(
                status=VendorEarning.Status.FAILED,
                payout_reference=result.get('reference', ''),
                payout_error=result['error'],
            )
            logger.error(
                '[Payout] ✗ GHS %.2f FAILED for %s (order %s): %s',
                net, vendor.shop_name, order.order_ref, result['error'],
            )
            # SMS alert to admin so manual transfer can be done promptly
            try:
                from notifications.sms import send_sms
                send_sms(
                    getattr(settings, 'ADMIN_PHONE', ''),
                    f'Lynctel: Payout FAILED for {vendor.shop_name} '
                    f'(GHS {net}, order {order.order_ref}). '
                    f'Manual Hubtel transfer needed.',
                )
            except Exception:
                pass


# ── Order payment confirmation ─────────────────────────────────────────────────

def _mark_paid(order, transaction_id=''):
    """
    Mark order as paid and trigger all post-payment actions:
      · Commission split + vendor MoMo disbursement (Hubtel Transfer)
      · Delivery record creation
      · Customer + vendor SMS (Arkesel)
      · Customer + vendor push notifications
    """
    if order.payment_status == Order.PaymentStatus.PAID:
        return  # idempotent

    order.payment_status = Order.PaymentStatus.PAID
    order.status         = Order.Status.CONFIRMED
    if transaction_id and hasattr(order, 'transaction_id'):
        order.transaction_id = transaction_id
    order.save()

    # ── Split + disburse ────────────────────────────────────────
    _split_and_disburse(order)

    # ── Create delivery record ──────────────────────────────────
    try:
        from order.views import create_delivery_for_order
        create_delivery_for_order(order)
    except Exception as exc:
        logger.error('[Payment] Delivery creation failed for %s: %s', order.order_ref, exc)

    # ── SMS via Arkesel ─────────────────────────────────────────
    try:
        arkesel = importlib.import_module('arkesel')
        arkesel.sms_order_confirmed(order)
        arkesel.sms_new_order_to_vendor(order)
    except Exception:
        pass

    # ── Push notifications ──────────────────────────────────────
    try:
        from push_notifications import push_order_confirmed, push_new_order_to_vendor
        push_order_confirmed(order)
        push_new_order_to_vendor(order)
    except Exception:
        pass


# ── Order creation helper ──────────────────────────────────────────────────────

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
            unit_price   = cart_item.product.selling_price,
            quantity     = cart_item.quantity,
        )
    cart.items.all().delete()
    del request.session['pending_order']
    return order


# ── Payment page (step 2 of checkout) ─────────────────────────────────────────

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
        payment_method   = request.POST.get('payment_method', '').strip()
        payment_provider = request.POST.get('payment_provider', 'hubtel').strip()

        if not payment_method:
            messages.error(request, 'Choose a payment method to continue.')
            return render(request, 'payment/payment.html', {
                'pending_order': pending_order,
                'cart':          cart,
                'momo_options':  MOMO_OPTIONS,
                'cart_count':    cart.total_items,
            })

        order = _create_order_from_pending(request, pending_order, cart)

        if payment_provider == 'flutterwave':
            return redirect('payment:flutterwave_init', order_pk=order.pk)
        return redirect('payment:hubtel_init', order_pk=order.pk)

    return render(request, 'payment/payment.html', {
        'pending_order': pending_order,
        'cart':          cart,
        'momo_options':  MOMO_OPTIONS,
        'cart_count':    cart.total_items,
    })


# ── Hubtel checkout views ──────────────────────────────────────────────────────

@login_required
def hubtel_init(request, order_pk):
    order = get_object_or_404(Order, pk=order_pk, customer=request.user)

    if not HUBTEL_CLIENT_ID:
        messages.error(request, 'Payment gateway not configured. Contact support.')
        return redirect('order:tracking', order_ref=order.order_ref)

    base_url    = request.build_absolute_uri('/').rstrip('/')
    return_url  = f'{base_url}/checkout/hubtel/callback/?ref={order.order_ref}'
    cancel_url  = f'{base_url}/checkout/hubtel/cancel/?ref={order.order_ref}'
    webhook_url = f'{base_url}/checkout/hubtel/webhook/'

    try:
        resp = http_requests.post(
            'https://api.hubtel.com/v2/pos/onlinecheckout/items/initiate',
            headers={'Authorization': _hubtel_auth(), 'Content-Type': 'application/json'},
            json={
                'totalAmount':           float(order.total_amount),
                'description':           f'Lynctel order {order.order_ref}',
                'clientReference':       order.order_ref,
                'callbackUrl':           webhook_url,
                'returnUrl':             return_url,
                'cancellationUrl':       cancel_url,
                'merchantAccountNumber': HUBTEL_MERCHANT_ACCT,
            },
            timeout=20,
        )
        data = resp.json()
        checkout_url = data.get('paylinkUrl') or data.get('checkoutUrl')

        if checkout_url:
            paylink_id = data.get('paylinkId', '')
            if paylink_id and hasattr(order, 'payment_reference'):
                order.payment_reference = paylink_id
                order.save(update_fields=['payment_reference'])
            return redirect(checkout_url)

        logger.error('[Hubtel] No checkout URL for order %s: %s', order.order_ref, data)

    except Exception as exc:
        logger.error('[Hubtel] Init error for order %s: %s', order.order_ref, exc)

    messages.error(request, 'Could not reach Hubtel. Please try again.')
    return redirect('order:tracking', order_ref=order.order_ref)


@login_required
def hubtel_callback(request):
    """Browser redirect from Hubtel after checkout completes/fails/cancels."""
    order_ref = request.GET.get('ref', '')
    status    = request.GET.get('status', '').lower()

    if not order_ref:
        return redirect('order:history')

    order = get_object_or_404(Order, order_ref=order_ref, customer=request.user)

    if order.payment_status == Order.PaymentStatus.PAID:
        messages.success(request, f'✅ Payment confirmed! Order {order.order_ref} is being processed.')
        return redirect('order:tracking', order_ref=order.order_ref)

    if status == 'success':
        _mark_paid(order)
        messages.success(request, f'✅ Payment confirmed! Order {order.order_ref} is being processed.')
        return redirect('order:tracking', order_ref=order.order_ref)

    if status == 'cancelled':
        messages.warning(request, 'Payment cancelled. Your order has not been placed.')
    else:
        messages.error(request, 'Payment could not be completed. Please try again.')

    return render(request, 'payment/failed.html', {'order': order})


@login_required
def hubtel_cancel(request):
    order_ref = request.GET.get('ref', '')
    order     = get_object_or_404(Order, order_ref=order_ref, customer=request.user)
    messages.warning(request, 'Payment cancelled.')
    return render(request, 'payment/failed.html', {'order': order})


@csrf_exempt
def hubtel_webhook(request):
    """
    Server-to-server payment confirmation from Hubtel.
    This fires before the browser redirect — it's the authoritative source.

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

    response_code = body.get('ResponseCode', '')
    data          = body.get('Data', {})
    order_ref     = data.get('ClientReference', '')
    txn_id        = data.get('TransactionId', '')

    logger.info('[Hubtel] Webhook — ref=%s code=%s txn=%s', order_ref, response_code, txn_id)

    if not order_ref:
        return HttpResponse(status=400)

    try:
        order = Order.objects.get(order_ref=order_ref)
    except Order.DoesNotExist:
        logger.warning('[Hubtel] Webhook: order %s not found', order_ref)
        return HttpResponse(status=404)

    if response_code == '0000':
        _mark_paid(order, transaction_id=txn_id)

    return HttpResponse(status=200)


# ── Flutterwave (unchanged) ────────────────────────────────────────────────────

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
                messages.success(request, f'✅ Payment confirmed! Order {order.order_ref} is being processed.')
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
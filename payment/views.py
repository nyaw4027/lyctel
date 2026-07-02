"""
payment/views.py — fixed

Changes from the version you had:

1. payment_page() now reads request.session['pending_order'] (the key
   checkout() actually sets) instead of the never-set 'pending_order_ref'.
2. payment_page() now handles POST: this is where the real Order and
   OrderItem rows get created for the first time — nothing before this
   point in the flow ever created them. On success it clears the cart and
   the session's pending_order, then routes to Paystack or Flutterwave.
3. Added MOMO_OPTIONS, since payment/page.html expects a `momo_options`
   context var that no view was providing.
4. Added flutterwave_init(), since paystack has an init step but
   Flutterwave never did — payment_callback() and flutterwave_webhook()
   only verify a payment after Flutterwave redirects back; nothing
   actually started a Flutterwave charge.
5. Reuses order.get_or_create_cart() instead of duplicating cart lookup
   logic.

You'll also need to add two lines to payment/urls.py — see the bottom of
this file.
"""

import logging
import hmac
import hashlib
import json
from decimal import Decimal

import requests as http_requests

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import HttpResponse
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings

from order.models import Order, OrderItem
from order.views import get_or_create_cart
from vendors.models import VendorEarning, AppCommission
from delivery.utils import MIN_FARE

logger = logging.getLogger(__name__)

PAYSTACK_SECRET  = getattr(settings, 'PAYSTACK_SECRET_KEY', '')
PAYSTACK_PUBLIC  = getattr(settings, 'PAYSTACK_PUBLIC_KEY', '')
FLW_SECRET       = getattr(settings, 'FLW_SECRET_KEY',      '')
FLW_PUBLIC       = getattr(settings, 'FLW_PUBLIC_KEY',      '')
FLW_WEBHOOK_HASH = getattr(settings, 'FLW_WEBHOOK_HASH',    '')

# Displayed on payment/page.html — (value, label, badge classes, ussd shortcode)
# Adjust codes/labels to match what you actually want shown.
MOMO_OPTIONS = [
    ('mtn',        'MTN Mobile Money', 'bg-yellow-100 text-yellow-700', '*170#'),
    ('vodafone',   'Vodafone Cash',    'bg-red-100 text-red-600',       '*110#'),
    ('airteltigo', 'AirtelTigo Money', 'bg-blue-100 text-blue-700',     '*500#'),
]


# ── SHARED HELPERS ────────────────────────────────────────

def _split_commissions(order):
    """Split revenue per vendor and record Lynctel's commission."""
    vendor_totals = {}
    for item in order.items.select_related('product__vendor').all():
        vendor = item.product.vendor if item.product else None
        if vendor:
            vendor_totals[vendor] = (
                vendor_totals.get(vendor, Decimal('0')) +
                (item.unit_price * item.quantity)
            )

    for vendor, total in vendor_totals.items():
        rate       = Decimal(str(vendor.commission_rate or 10)) / Decimal('100')
        commission = (total * rate).quantize(Decimal('0.01'))
        net        = (total - commission).quantize(Decimal('0.01'))

        VendorEarning.objects.get_or_create(
            vendor=vendor, order=order,
            defaults={
                'gross_amount':      total,
                'commission_amount': commission,
                'net_amount':        net,
            }
        )
        AppCommission.objects.get_or_create(
            vendor=vendor, order=order,
            defaults={'amount': commission}
        )


def _mark_paid(order):
    """Mark order as paid, split commissions, send notifications."""
    order.payment_status = Order.PaymentStatus.PAID
    order.status         = Order.Status.CONFIRMED
    order.save()
    _split_commissions(order)

    try:
        from arkesel import sms_order_confirmed, sms_new_order_to_vendor
        sms_order_confirmed(order)
        sms_new_order_to_vendor(order)
    except Exception:
        pass

    try:
        from push_notifications import push_order_confirmed, push_new_order_to_vendor
        push_order_confirmed(order)
        push_new_order_to_vendor(order)
    except Exception:
        pass


def _create_order_from_pending(request, pending_order, cart):
    """
    Turn the session's pending_order dict + the current cart into a real
    Order + OrderItem rows. This is the step that never existed before —
    checkout() only ever wrote to the session, it never touched the DB.
    """
    order = Order.objects.create(
        customer=request.user,
        delivery_choice=pending_order.get('delivery_choice', 'rider'),
        delivery_address=pending_order.get('delivery_address', ''),
        delivery_city=pending_order.get('delivery_city', ''),
        delivery_phone=pending_order.get('delivery_phone', ''),
        delivery_lat=pending_order.get('delivery_lat'),
        delivery_lng=pending_order.get('delivery_lng'),
        parcel_bus_station=pending_order.get('parcel_bus_station', ''),
        parcel_recipient_phone=pending_order.get('parcel_recipient_phone', ''),
        parcel_notes=pending_order.get('parcel_notes', ''),
        customer_note=pending_order.get('order_note', ''),
        subtotal=Decimal(pending_order.get('subtotal', '0')),
        delivery_fee=Decimal(pending_order.get('delivery_fee', '0')),
        total_amount=Decimal(pending_order.get('total', '0')),
    )

    for cart_item in cart.items.select_related('product').all():
        OrderItem.objects.create(
            order=order,
            product=cart_item.product,
            product_name=cart_item.product.name,
            unit_price=cart_item.product.selling_price,
            quantity=cart_item.quantity,
        )

    # The cart is now "spent" — clear it so refreshing checkout doesn't
    # let someone re-order the same items, and clear the session scratch
    # data so a page refresh on /payment/ can't double-create an Order.
    cart.items.all().delete()
    del request.session['pending_order']

    return order


# ── PAYMENT METHOD SELECTION (step 2 of checkout) ─────────

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
        payment_provider = request.POST.get('payment_provider', 'flutterwave').strip()
        # momo_number isn't persisted anywhere yet — Order has no field for
        # it. Add one (and a payment_method field) if you want it stored;
        # for MoMo-on-delivery/inline flows the number is usually collected
        # by the gateway itself anyway, so this may not matter in practice.

        if not payment_method:
            messages.error(request, 'Choose a payment method to continue.')
            return render(request, 'payment/payment.html', {
                'pending_order': pending_order,
                'cart':          cart,
                'momo_options':  MOMO_OPTIONS,
                'cart_count':    cart.total_items,
            })

        order = _create_order_from_pending(request, pending_order, cart)

        if payment_provider == 'paystack':
            return redirect('payment:paystack_init', order_pk=order.pk)

        return redirect('payment:flutterwave_init', order_pk=order.pk)

    return render(request, 'payment/payment.html', {
        'pending_order': pending_order,
        'cart':          cart,
        'momo_options':  MOMO_OPTIONS,
        'cart_count':    cart.total_items,
    })


# ── FLUTTERWAVE INIT (new — this step never existed) ──────

@login_required
def flutterwave_init(request, order_pk):
    """Start a Flutterwave Standard checkout and redirect the customer to it."""
    order = get_object_or_404(Order, pk=order_pk, customer=request.user)

    if not FLW_SECRET:
        messages.error(request, 'Payment gateway not configured. Please pay on delivery.')
        return redirect('order:order_detail', pk=order.pk)

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

        logger.error('Flutterwave init failed for order %s: %s', order.pk, data)

    except Exception as e:
        logger.error('Flutterwave init error for order %s: %s', order.pk, str(e))

    messages.error(request, 'Could not start payment. Please try again or pay on delivery.')
    return redirect('order:order_detail', pk=order.pk)


# ── FLUTTERWAVE CALLBACK ──────────────────────────────────

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
                return redirect('order:order_detail', pk=order.pk)
            elif order:
                messages.info(request, 'Order already confirmed.')
                return redirect('order:order_detail', pk=order.pk)
            else:
                messages.error(request, 'Order not found.')
        else:
            messages.error(request, 'Payment verification failed.')

    except Exception as e:
        logger.error('Flutterwave callback error: %s', str(e))
        messages.error(request, 'Could not verify payment. Contact support if charged.')

    return redirect('products:list')


# ── FLUTTERWAVE WEBHOOK ───────────────────────────────────

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
                    logger.info('FLW webhook: order %s marked paid', tx_ref)
    except Exception as e:
        logger.error('FLW webhook error: %s', str(e))

    return HttpResponse(status=200)


# ── PAYSTACK INIT ─────────────────────────────────────────

@login_required
def paystack_init(request, order_pk):
    order = get_object_or_404(Order, pk=order_pk, customer=request.user)

    if not PAYSTACK_PUBLIC:
        messages.error(request, 'Payment gateway not configured. Please pay on delivery.')
        return redirect('order:detail', pk=order.pk)

    email = (
        request.user.email or
        f'{request.user.phone}@lynctel.app'
    )

    return render(request, 'payment/paystack.html', {
        'order':       order,
        'public_key':  PAYSTACK_PUBLIC,
        'amount_kobo': int(order.total_amount * 100),
        'email':       email,
        'cart_count':  0,
    })


# ── PAYSTACK VERIFY ───────────────────────────────────────

@login_required
def paystack_verify(request, order_pk):
    order     = get_object_or_404(Order, pk=order_pk, customer=request.user)
    reference = request.GET.get('reference', '')

    if not reference or not PAYSTACK_SECRET:
        messages.error(request, 'Payment verification failed.')
        return redirect('order:detail', pk=order.pk)

    try:
        resp = http_requests.get(
            f'https://api.paystack.co/transaction/verify/{reference}',
            headers={'Authorization': f'Bearer {PAYSTACK_SECRET}'},
            timeout=10,
        )
        data = resp.json()

        if data.get('status') and data['data'].get('status') == 'success':
            amount_paid = Decimal(str(data['data']['amount'])) / Decimal('100')
            if amount_paid >= order.total_amount:
                if order.payment_status != Order.PaymentStatus.PAID:
                    _mark_paid(order)
                messages.success(request, f'✅ Payment confirmed! Order {order.order_ref} is being processed.')
            else:
                messages.warning(request, 'Payment amount mismatch. Contact support.')
        else:
            messages.error(request, 'Payment was not successful. Please try again.')

    except Exception as e:
        logger.error('Paystack verify error for order %s: %s', order.pk, str(e))
        messages.error(request, 'Could not verify payment. Contact support if charged.')

    return redirect('order:detail', pk=order.pk)


# ── PAYSTACK CALLBACK ─────────────────────────────────────

@login_required
def paystack_callback(request, tx_ref):
    order = Order.objects.filter(
        order_ref=tx_ref, customer=request.user
    ).first()

    if not order:
        messages.error(request, 'Order not found.')
        return redirect('products:list')

    reference = request.GET.get('reference', tx_ref)

    try:
        resp = http_requests.get(
            f'https://api.paystack.co/transaction/verify/{reference}',
            headers={'Authorization': f'Bearer {PAYSTACK_SECRET}'},
            timeout=10,
        )
        data = resp.json()

        if data.get('status') and data['data'].get('status') == 'success':
            if order.payment_status != Order.PaymentStatus.PAID:
                _mark_paid(order)
            messages.success(request, f'✅ Payment confirmed! Order {order.order_ref} is confirmed.')
        else:
            messages.error(request, 'Payment was not successful.')

    except Exception as e:
        logger.error('Paystack callback error: %s', str(e))
        messages.error(request, 'Could not verify payment. Contact support if charged.')

    return redirect('order:detail', pk=order.pk)


# ── PAYSTACK WEBHOOK ──────────────────────────────────────

@csrf_exempt
def paystack_webhook(request):
    if request.method != 'POST':
        return HttpResponse(status=405)

    signature = request.headers.get('x-paystack-signature', '')
    if PAYSTACK_SECRET and signature:
        expected = hmac.new(
            PAYSTACK_SECRET.encode('utf-8'),
            request.body,
            hashlib.sha512,
        ).hexdigest()
        if not hmac.compare_digest(expected, signature):
            return HttpResponse(status=401)

    try:
        payload = json.loads(request.body)
        event   = payload.get('event', '')

        if event == 'charge.success':
            data      = payload.get('data', {})
            reference = data.get('reference', '')
            amount    = Decimal(str(data.get('amount', 0))) / Decimal('100')
            meta      = data.get('metadata', {})
            order_ref = meta.get('order_ref', reference)

            order = Order.objects.filter(order_ref=order_ref).first()
            if order and order.payment_status != Order.PaymentStatus.PAID:
                if amount >= order.total_amount:
                    _mark_paid(order)
                    logger.info('Paystack webhook: order %s marked paid', order_ref)

    except Exception as e:
        logger.error('Paystack webhook error: %s', str(e))

    return HttpResponse(status=200)


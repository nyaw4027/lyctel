import logging
import hmac
import hashlib
import json
from decimal import Decimal, InvalidOperation

import requests as http_requests

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.conf import settings
from django.utils import timezone

from cart.models import Cart, CartItem
from order.models import Order, OrderItem
from vendors.models import Vendor, VendorEarning, AppCommission
from delivery.models import Delivery
from delivery.utils import (
    haversine_distance,
    calculate_delivery_fee,
    estimate_eta_minutes,
    calculate_rider_commission,
    calculate_app_cut,
    MIN_FARE,
)

logger = logging.getLogger(__name__)

PAYSTACK_SECRET  = getattr(settings, 'PAYSTACK_SECRET_KEY', '')
PAYSTACK_PUBLIC  = getattr(settings, 'PAYSTACK_PUBLIC_KEY', '')
FLW_SECRET       = getattr(settings, 'FLW_SECRET_KEY', '')
FLW_PUBLIC       = getattr(settings, 'FLW_PUBLIC_KEY', '')
FLW_WEBHOOK_HASH = getattr(settings, 'FLW_WEBHOOK_HASH', '')

MOMO_OPTIONS = [
    ('mtn_momo',     'MTN Mobile Money',    'bg-yellow-100 text-yellow-700', '*170#'),
    ('vodafone',     'Vodafone Cash',       'bg-red-100 text-red-600',       '*110#'),
    ('airteltigo',   'AirtelTigo Money',    'bg-blue-100 text-blue-700',     '*500#'),
]


# ── HELPERS ───────────────────────────────────────────────

def _get_cart(request):
    if request.user.is_authenticated:
        cart, _ = Cart.objects.get_or_create(user=request.user)
    else:
        if not request.session.session_key:
            request.session.create()
        cart, _ = Cart.objects.get_or_create(
            session_key=request.session.session_key, user=None
        )
    return cart


def _split_commissions(order):
    vendor_totals = {}
    for item in order.items.select_related('product__vendor').all():
        vendor = item.product.vendor if item.product else None
        if vendor:
            vendor_totals[vendor] = vendor_totals.get(vendor, Decimal('0')) + (item.price * item.quantity)

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
    order.payment_status = Order.PaymentStatus.PAID
    order.status         = Order.Status.CONFIRMED
    order.save()
    _split_commissions(order)

    try:
        from push_notifications import push_order_confirmed, push_new_order_to_vendor
        push_order_confirmed(order)
        push_new_order_to_vendor(order)
    except Exception:
        pass


# ── PAYMENT PAGE (step 2 of checkout) ────────────────────
# The order/views.py checkout() saves delivery details to the session as
# 'pending_order' and redirects here. This view creates the real Order
# row and lets the customer choose payment method.

@login_required
def payment_page(request):
    pending = request.session.get('pending_order')
    if not pending:
        messages.warning(request, 'Your session expired. Please fill in your delivery details again.')
        return redirect('order:checkout')

    cart = _get_cart(request)
    if not cart.items.exists():
        messages.warning(request, 'Your cart is empty.')
        return redirect('products:list')

    subtotal     = Decimal(pending['subtotal'])
    delivery_fee = Decimal(pending['delivery_fee'])
    total        = Decimal(pending['total'])

    if request.method == 'POST':
        pay_method = request.POST.get('payment_method', '')
        if not pay_method:
            messages.error(request, 'Please select a payment method.')
            return redirect('payment:page')

        # Create the Order now that we have payment method
        order = Order.objects.create(
            customer         = request.user,
            delivery_address = pending.get('delivery_address', ''),
            delivery_city    = pending.get('delivery_city', ''),
            delivery_phone   = pending.get('delivery_phone', ''),
            delivery_lat     = pending.get('delivery_lat'),
            delivery_lng     = pending.get('delivery_lng'),
            delivery_fee     = delivery_fee,
            subtotal         = subtotal,
            total_amount     = total,
            payment_method   = pay_method,
            payment_status   = Order.PaymentStatus.UNPAID,
            status           = Order.Status.PENDING,
            delivery_choice  = pending.get('delivery_choice', 'rider'),
            order_note       = pending.get('order_note', ''),
            parcel_bus_station     = pending.get('parcel_bus_station', ''),
            parcel_recipient_phone = pending.get('parcel_recipient_phone', ''),
            parcel_notes           = pending.get('parcel_notes', ''),
        )

        for cart_item in cart.items.select_related('product').all():
            OrderItem.objects.create(
                order    = order,
                product  = cart_item.product,
                quantity = cart_item.quantity,
                price    = cart_item.product.selling_price,
                subtotal = cart_item.subtotal,
            )

        cart.items.all().delete()
        del request.session['pending_order']

        # Cash on delivery — mark paid immediately
        if pay_method == 'cash':
            _mark_paid(order)
            messages.success(request, f'✅ Order {order.order_ref} placed! Pay on delivery.')
            return redirect('order:confirmation', order_ref=order.order_ref)

        # Paystack — redirect to inline popup
        return redirect('payment:paystack_init', order_pk=order.pk)

    # GET — show payment method selection
    return render(request, 'payment/payment.html', {
        'pending_order': pending,
        'cart':          cart,
        'momo_options':  MOMO_OPTIONS,
        'cart_count':    cart.total_items,
    })


# ── PAYSTACK INIT ─────────────────────────────────────────

@login_required
def paystack_init(request, order_pk):
    order = get_object_or_404(Order, pk=order_pk, customer=request.user)

    if not PAYSTACK_PUBLIC:
        messages.error(request, 'Payment gateway not configured. Contact support.')
        return redirect('order:confirmation', order_ref=order.order_ref)

    if order.payment_status == Order.PaymentStatus.PAID:
        return redirect('order:confirmation', order_ref=order.order_ref)

    return render(request, 'payment/pay.html', {
        'order':       order,
        'public_key':  PAYSTACK_PUBLIC,
        'amount_kobo': int(order.total_amount * 100),
        'email':       getattr(request.user, 'email', None) or f'{request.user.phone}@lynctel.app',
        'cart_count':  0,
    })


# ── PAYSTACK VERIFY (callback from inline popup) ──────────

@login_required
def paystack_verify(request, order_pk):
    order     = get_object_or_404(Order, pk=order_pk, customer=request.user)
    reference = request.GET.get('reference', '')

    if not reference or not PAYSTACK_SECRET:
        messages.error(request, 'Payment verification failed.')
        return redirect('order:confirmation', order_ref=order.order_ref)

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

    return redirect('order:confirmation', order_ref=order.order_ref)


# ── PAYSTACK CALLBACK (redirect from Paystack page) ───────

@login_required
def paystack_callback(request, tx_ref):
    order = Order.objects.filter(order_ref=tx_ref, customer=request.user).first()
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

    return redirect('order:confirmation', order_ref=order.order_ref)


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
        if payload.get('event') == 'charge.success':
            data      = payload.get('data', {})
            reference = data.get('reference', '')
            amount    = Decimal(str(data.get('amount', 0))) / Decimal('100')

            if reference:
                meta      = data.get('metadata', {})
                order_ref = meta.get('order_ref', reference)
                order     = Order.objects.filter(order_ref=order_ref).first()

                if order and order.payment_status != Order.PaymentStatus.PAID:
                    if amount >= order.total_amount:
                        _mark_paid(order)
                        logger.info('Paystack webhook: order %s marked paid', order_ref)

    except Exception as e:
        logger.error('Paystack webhook error: %s', str(e))

    return HttpResponse(status=200)


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
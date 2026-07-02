import logging
import hmac
import hashlib
import json
from decimal import Decimal, InvalidOperation

import requests as http_requests

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings

from order.models import Order
from vendors.models import VendorEarning, AppCommission
from delivery.utils import MIN_FARE

logger = logging.getLogger(__name__)

PAYSTACK_SECRET  = getattr(settings, 'PAYSTACK_SECRET_KEY', '')
PAYSTACK_PUBLIC  = getattr(settings, 'PAYSTACK_PUBLIC_KEY', '')
FLW_SECRET       = getattr(settings, 'FLW_SECRET_KEY',      '')
FLW_PUBLIC       = getattr(settings, 'FLW_PUBLIC_KEY',      '')
FLW_WEBHOOK_HASH = getattr(settings, 'FLW_WEBHOOK_HASH',    '')


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


# ── FLUTTERWAVE PAYMENT PAGE ──────────────────────────────

@login_required
def payment_page(request):
    """Legacy Flutterwave payment page — kept for backward compatibility."""
    pending_order_ref = request.session.get('pending_order_ref')
    if pending_order_ref:
        order = Order.objects.filter(
            order_ref=pending_order_ref,
            customer=request.user
        ).first()
        if order:
            return render(request, 'payment/payment.html', {
                'order':      order,
                'flw_public': FLW_PUBLIC,
                'cart_count': 0,
            })

    messages.warning(request, 'No pending order found.')
    return redirect('products:list')


# ── FLUTTERWAVE CALLBACK ──────────────────────────────────

@login_required
def payment_callback(request):
    tx_ref   = request.GET.get('tx_ref', '')
    status   = request.GET.get('status', '')
    trans_id = request.GET.get('transaction_id', '')

    if status != 'successful':
        messages.error(request, 'Payment was not successful. Please try again.')
        return redirect('payment:page')

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
                return redirect('order:detail', pk=order.pk)
            elif order:
                messages.info(request, 'Order already confirmed.')
                return redirect('order:detail', pk=order.pk)
        else:
            messages.error(request, 'Payment verification failed.')

    except Exception as e:
        logger.error('Flutterwave callback error: %s', str(e))
        messages.error(request, 'Could not verify payment. Contact support if charged.')

    return redirect('payment:page')


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
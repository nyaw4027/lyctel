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
    haversine_distance, calculate_delivery_fee,
    estimate_eta_minutes, calculate_rider_commission,
    calculate_app_cut, MIN_FARE,
)

logger = logging.getLogger(__name__)

LOCATIONIQ_KEY    = getattr(settings, 'LOCATIONIQ_API_KEY',   '')
PAYSTACK_SECRET   = getattr(settings, 'PAYSTACK_SECRET_KEY',  '')
PAYSTACK_PUBLIC   = getattr(settings, 'PAYSTACK_PUBLIC_KEY',  '')
FLW_SECRET        = getattr(settings, 'FLW_SECRET_KEY',       '')
FLW_PUBLIC        = getattr(settings, 'FLW_PUBLIC_KEY',       '')
FLW_WEBHOOK_HASH  = getattr(settings, 'FLW_WEBHOOK_HASH',     '')


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
            vendor_totals[vendor] = vendor_totals.get(vendor, Decimal('0')) + item.get_total_price()

    for vendor, total in vendor_totals.items():
        rate       = Decimal(str(vendor.commission_rate or 10)) / Decimal('100')
        commission = (total * rate).quantize(Decimal('0.01'))
        net        = (total - commission).quantize(Decimal('0.01'))

        VendorEarning.objects.get_or_create(
            vendor=vendor, order=order,
            defaults={
                'gross_amount': total,
                'commission_amount': commission,
                'net_amount': net,
            }
        )
        AppCommission.objects.get_or_create(
            vendor=vendor, order=order,
            defaults={'amount': commission}
        )


def _pick_vendor_location(order):
    first_item = order.items.select_related('product__vendor').first()
    if first_item and first_item.product and first_item.product.vendor:
        v = first_item.product.vendor
        if v.latitude and v.longitude:
            return float(v.latitude), float(v.longitude)
    return 5.6037, -0.1870  # Accra fallback


def _pick_vendor_location_from_items(cart_items):
    for item in cart_items:
        if item.product and item.product.vendor:
            v = item.product.vendor
            if v.latitude and v.longitude:
                return float(v.latitude), float(v.longitude)
    return 5.6037, -0.1870


def _mark_paid(order):
    order.payment_status = 'paid'
    order.status         = 'confirmed'
    order.save()
    _split_commissions(order)

    try:
        from push_notifications import push_order_confirmed, push_new_order_to_vendor
        push_order_confirmed(order)
        push_new_order_to_vendor(order)
    except Exception:
        pass


# ── CHECKOUT (distance-based, with LocationIQ map) ────────

@login_required
def checkout(request):
    cart       = _get_cart(request)
    cart_items = cart.items.select_related('product__images').all()

    if not cart_items.exists():
        messages.warning(request, 'Your cart is empty.')
        return redirect('products:list')

    subtotal = sum(item.get_total_price() for item in cart_items)

    if request.method == 'POST':
        first_name  = request.POST.get('first_name', '').strip()
        last_name   = request.POST.get('last_name', '').strip()
        phone       = request.POST.get('phone', '').strip()
        address     = request.POST.get('delivery_address', '').strip()
        city        = request.POST.get('delivery_city', '').strip()
        pay_method  = request.POST.get('payment_method', 'cash')
        dlat        = request.POST.get('delivery_lat', '').strip()
        dlng        = request.POST.get('delivery_lng', '').strip()
        fee_posted  = request.POST.get('delivery_fee', '0').strip()
        dist_posted = request.POST.get('distance_km', '0').strip()
        note        = request.POST.get('order_note', '').strip()

        errors = {}
        if not first_name: errors['first_name'] = 'First name is required.'
        if not phone:      errors['phone']       = 'Phone number is required.'
        if not address:    errors['address']     = 'Delivery address is required.'
        if not city:       errors['city']        = 'City is required.'

        if errors:
            return render(request, 'payment/checkout.html', {
                'cart_items':     cart_items,
                'subtotal':       subtotal,
                'default_fee':    str(MIN_FARE),
                'errors':         errors,
                'form_data':      request.POST,
                'locationiq_key': LOCATIONIQ_KEY,
                'cart_count':     cart.total_items,
                'user':           request.user,
            })

        # Delivery fee — recalculate server-side from coordinates
        try:
            delivery_fee = Decimal(fee_posted)
            if delivery_fee <= 0:
                delivery_fee = MIN_FARE
        except (InvalidOperation, ValueError):
            delivery_fee = MIN_FARE

        try:
            distance_km = float(dist_posted) if dist_posted else None
        except ValueError:
            distance_km = None

        if dlat and dlng:
            try:
                vendor_lat, vendor_lng = _pick_vendor_location_from_items(cart_items)
                distance_km  = haversine_distance(
                    vendor_lat, vendor_lng, float(dlat), float(dlng)
                )
                delivery_fee = calculate_delivery_fee(distance_km)
            except Exception:
                pass

        total_amount = subtotal + delivery_fee

        # Create order
        order = Order.objects.create(
            customer         = request.user,
            first_name       = first_name,
            last_name        = last_name,
            phone            = phone,
            delivery_address = address,
            delivery_city    = city,
            delivery_lat     = float(dlat) if dlat else None,
            delivery_lng     = float(dlng) if dlng else None,
            delivery_fee     = delivery_fee,
            subtotal         = subtotal,
            total_amount     = total_amount,
            payment_method   = pay_method,
            payment_status   = 'unpaid',
            status           = 'pending',
            order_note       = note,
        )

        for cart_item in cart_items:
            OrderItem.objects.create(
                order    = order,
                product  = cart_item.product,
                quantity = cart_item.quantity,
                price    = cart_item.product.selling_price,
            )

        # Create delivery record (no zone)
        vendor_lat, vendor_lng = _pick_vendor_location(order)
        Delivery.objects.create(
            booker           = request.user,
            pickup_location  = 'Vendor location',
            dropoff_location = f'{address}, {city}',
            pickup_lat       = vendor_lat,
            pickup_lng       = vendor_lng,
            dropoff_lat      = float(dlat) if dlat else None,
            dropoff_lng      = float(dlng) if dlng else None,
            delivery_fee     = delivery_fee,
            rider_commission = calculate_rider_commission(delivery_fee),
            distance_km      = distance_km,
            zone             = None,
            delivery_type    = Delivery.DeliveryType.STANDARD,
            status           = Delivery.Status.PENDING,
            delivery_note    = note,
        )

        if pay_method == 'cash':
            _mark_paid(order)
            cart.items.all().delete()
            messages.success(request, f'✅ Order {order.order_ref} placed! Pay on delivery.')
            return redirect('order:detail', pk=order.pk)

        elif pay_method == 'paystack':
            cart.items.all().delete()
            return redirect('payment:paystack_init', order_pk=order.pk)

        else:
            cart.items.all().delete()
            messages.success(request, f'✅ Order {order.order_ref} placed!')
            return redirect('order:detail', pk=order.pk)

    return render(request, 'payment/checkout.html', {
        'cart_items':     cart_items,
        'subtotal':       subtotal,
        'default_fee':    str(MIN_FARE),
        'locationiq_key': LOCATIONIQ_KEY,
        'cart_count':     cart.total_items,
        'user':           request.user,
    })


# ── FLUTTERWAVE PAYMENT PAGE ──────────────────────────────

@login_required
def payment_page(request):
    cart       = _get_cart(request)
    cart_items = cart.items.select_related('product').all()

    if not cart_items.exists():
        messages.warning(request, 'Your cart is empty.')
        return redirect('products:list')

    subtotal     = sum(item.get_total_price() for item in cart_items)
    delivery_fee = MIN_FARE
    total        = subtotal + delivery_fee

    return render(request, 'payment/payment.html', {
        'cart_items':   cart_items,
        'subtotal':     subtotal,
        'delivery_fee': delivery_fee,
        'total':        total,
        'flw_public':   FLW_PUBLIC,
        'cart_count':   cart.total_items,
        'user':         request.user,
    })


# ── FLUTTERWAVE CALLBACK ──────────────────────────────────

@login_required
def payment_callback(request):
    tx_ref     = request.GET.get('tx_ref', '')
    status     = request.GET.get('status', '')
    trans_id   = request.GET.get('transaction_id', '')

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
            if order and order.payment_status != 'paid':
                _mark_paid(order)
                messages.success(request, f'Payment confirmed! Order {order.order_ref} is being processed.')
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
                if order and order.payment_status != 'paid':
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

    return render(request, 'payment/paystack.html', {
        'order':       order,
        'public_key':  PAYSTACK_PUBLIC,
        'amount_kobo': int(order.total_amount * 100),
        'email':       request.user.email or f'{request.user.phone}@lynctel.app',
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


# ── PAYSTACK CALLBACK (redirect from Paystack) ────────────

@login_required
def paystack_callback(request, tx_ref):
    """
    Paystack redirects here after payment.
    tx_ref is our order_ref stored in the transaction metadata.
    """
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
            if order.payment_status != 'paid':
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

    # Verify signature
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

            if reference:
                # Try matching by order_ref stored in metadata
                meta      = data.get('metadata', {})
                order_ref = meta.get('order_ref', reference)
                order     = Order.objects.filter(order_ref=order_ref).first()

                if order and order.payment_status != 'paid':
                    if amount >= order.total_amount:
                        _mark_paid(order)
                        logger.info('Paystack webhook: order %s marked paid', order_ref)

    except Exception as e:
        logger.error('Paystack webhook error: %s', str(e))

    return HttpResponse(status=200)
import logging
from decimal import Decimal, InvalidOperation

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.conf import settings

from cart.models import Cart, CartItem
from order.models import Order, OrderItem
from vendors.models import Vendor, VendorEarning, AppCommission
from delivery.models import Delivery
from delivery.utils import (
    haversine_distance, calculate_delivery_fee,
    estimate_eta_minutes, calculate_rider_commission, calculate_app_cut,
    MIN_FARE,
)

logger = logging.getLogger(__name__)

LOCATIONIQ_KEY = getattr(settings, 'LOCATIONIQ_API_KEY', '')


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
    """
    Split revenue per vendor and record Lynctel's commission.
    Called after payment is confirmed.
    """
    vendor_totals = {}
    for item in order.items.select_related('product__vendor').all():
        vendor = item.product.vendor if item.product else None
        if vendor:
            vendor_totals[vendor] = vendor_totals.get(vendor, Decimal('0')) + item.get_total_price()

    for vendor, total in vendor_totals.items():
        rate       = Decimal(str(vendor.commission_rate or 10)) / Decimal('100')
        commission = (total * rate).quantize(Decimal('0.01'))
        net        = (total - commission).quantize(Decimal('0.01'))

        VendorEarning.objects.create(
            vendor=vendor, order=order,
            gross_amount=total, commission_amount=commission, net_amount=net,
        )
        AppCommission.objects.create(
            vendor=vendor, order=order, amount=commission,
        )


def _pick_vendor_location(order):
    """
    Returns (lat, lng) of the primary vendor for this order,
    falling back to a central Accra coordinate if none is set.
    """
    first_item = order.items.select_related('product__vendor').first()
    if first_item and first_item.product and first_item.product.vendor:
        vendor = first_item.product.vendor
        if vendor.latitude and vendor.longitude:
            return float(vendor.latitude), float(vendor.longitude)
    # Fallback: Accra city centre
    return 5.6037, -0.1870


# ── CHECKOUT ──────────────────────────────────────────────

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
                'cart_items':      cart_items,
                'subtotal':        subtotal,
                'default_fee':     str(MIN_FARE),
                'errors':          errors,
                'form_data':       request.POST,
                'locationiq_key':  LOCATIONIQ_KEY,
                'cart_count':      cart.total_items,
            })

        # ── Delivery fee calculation ──────────────────────
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

        # Recalculate server-side if coordinates were posted
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

        # ── Create Order ──────────────────────────────────
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

        # ── Create Order Items ────────────────────────────
        for cart_item in cart_items:
            OrderItem.objects.create(
                order    = order,
                product  = cart_item.product,
                quantity = cart_item.quantity,
                price    = cart_item.product.selling_price,
            )

        # ── Create Delivery record (no zone needed) ───────
        vendor_lat, vendor_lng = _pick_vendor_location(order)

        rider_commission = calculate_rider_commission(delivery_fee)
        app_cut          = calculate_app_cut(delivery_fee)

        Delivery.objects.create(
            booker            = request.user,
            pickup_location   = 'Vendor location',
            dropoff_location  = f'{address}, {city}',
            pickup_lat        = vendor_lat,
            pickup_lng        = vendor_lng,
            dropoff_lat       = float(dlat) if dlat else None,
            dropoff_lng       = float(dlng) if dlng else None,
            delivery_fee      = delivery_fee,
            rider_commission  = rider_commission,
            distance_km       = distance_km,
            zone              = None,
            delivery_type     = Delivery.DeliveryType.STANDARD,
            status            = Delivery.Status.PENDING,
            delivery_note     = note,
        )

        # ── Handle payment ────────────────────────────────
        if pay_method == 'cash':
            _mark_paid(order)
            cart.items.all().delete()
            messages.success(request, f'Order {order.order_ref} placed! Pay on delivery.')
            return redirect('order:detail', pk=order.pk)

        elif pay_method == 'paystack':
            request.session['pending_order_id'] = order.pk
            cart.items.all().delete()
            return redirect('payment:paystack_init', order_pk=order.pk)

        else:
            cart.items.all().delete()
            messages.success(request, f'Order {order.order_ref} placed!')
            return redirect('order:detail', pk=order.pk)

    return render(request, 'payment/checkout.html', {
        'cart_items':     cart_items,
        'subtotal':       subtotal,
        'default_fee':    str(MIN_FARE),
        'locationiq_key': LOCATIONIQ_KEY,
        'cart_count':     cart.total_items,
        'user':           request.user,
    })


def _pick_vendor_location_from_items(cart_items):
    """Get vendor coordinates from cart items queryset."""
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


# ── PAYSTACK INTEGRATION ──────────────────────────────────

@login_required
def paystack_init(request, order_pk):
    order = get_object_or_404(Order, pk=order_pk, customer=request.user)

    paystack_key = getattr(settings, 'PAYSTACK_PUBLIC_KEY', '')
    if not paystack_key:
        messages.error(request, 'Payment gateway not configured. Please pay on delivery.')
        return redirect('order:detail', pk=order.pk)

    return render(request, 'payment/paystack.html', {
        'order':       order,
        'public_key':  paystack_key,
        'amount_kobo': int(order.total_amount * 100),
        'email':       request.user.email or f'{request.user.phone}@lynctel.app',
        'cart_count':  0,
    })


@login_required
def paystack_verify(request, order_pk):
    import requests as http_requests

    order          = get_object_or_404(Order, pk=order_pk, customer=request.user)
    reference      = request.GET.get('reference', '')
    paystack_secret = getattr(settings, 'PAYSTACK_SECRET_KEY', '')

    if not reference or not paystack_secret:
        messages.error(request, 'Payment verification failed.')
        return redirect('order:detail', pk=order.pk)

    try:
        resp = http_requests.get(
            f'https://api.paystack.co/transaction/verify/{reference}',
            headers={'Authorization': f'Bearer {paystack_secret}'},
            timeout=10,
        )
        data = resp.json()

        if data.get('status') and data['data'].get('status') == 'success':
            amount_paid = Decimal(str(data['data']['amount'])) / Decimal('100')

            if amount_paid >= order.total_amount:
                _mark_paid(order)
                messages.success(request, f'Payment confirmed! Order {order.order_ref} is being processed.')
            else:
                messages.warning(request, 'Payment amount mismatch. Contact support.')
        else:
            messages.error(request, 'Payment was not successful. Please try again.')

    except Exception as e:
        logger.error('Paystack verify error for order %s: %s', order.pk, str(e))
        messages.error(request, 'Could not verify payment. Contact support if charged.')

    return redirect('order:detail', pk=order.pk)
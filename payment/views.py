import hmac
import hashlib
import json
import uuid
import requests

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.http import HttpResponse
from django.conf import settings
from django.utils import timezone

from cart.models import Cart, CartItem
from order.models import Order, OrderItem
from .models import Payment


def get_or_create_cart(request):
    if request.user.is_authenticated:
        cart, _ = Cart.objects.get_or_create(user=request.user)
    else:
        if not request.session.session_key:
            request.session.create()
        cart, _ = Cart.objects.get_or_create(
            session_key=request.session.session_key, user=None
        )
    return cart


@login_required
def payment_page(request):
    cart          = get_or_create_cart(request)
    pending_order = request.session.get('pending_order')

    if not pending_order or cart.total_items == 0:
        messages.warning(request, 'Please complete your delivery details first.')
        return redirect('order:checkout')

    if request.method == 'POST':
        payment_method = request.POST.get('payment_method')
        momo_number    = request.POST.get('momo_number', '').strip()

        # Create the Order
        order = Order.objects.create(
            customer         = request.user,
            delivery_address = pending_order['delivery_address'],
            delivery_city    = pending_order['delivery_city'],
            delivery_phone   = pending_order['delivery_phone'],
            subtotal         = pending_order['subtotal'],
            delivery_fee     = pending_order['delivery_fee'],
            total_amount     = pending_order['total'],
            status           = Order.Status.PENDING,
            payment_status   = Order.PaymentStatus.UNPAID,
        )

        # Snapshot cart → OrderItems + deduct stock
        for item in cart.items.select_related('product').all():
            OrderItem.objects.create(
                order        = order,
                product      = item.product,
                product_name = item.product.name,
                unit_price   = item.product.selling_price,
                quantity     = item.quantity,
            )
            item.product.stock_qty -= item.quantity
            item.product.save()

        # Create pending Payment record
        tx_ref  = f"LYN-{order.order_ref}-{uuid.uuid4().hex[:6].upper()}"
        payment = Payment.objects.create(
            order          = order,
            method         = payment_method,
            amount         = pending_order['total'],
            transaction_id = tx_ref,
            momo_number    = momo_number,
            status         = Payment.Status.PENDING,
        )

        # Clear cart + session
        cart.items.all().delete()
        del request.session['pending_order']

        # Build Flutterwave config
        network_map = {
            'mtn_momo':      'MTN',
            'vodafone_cash': 'VDF',
            'airteltigo':    'ATL',
        }
        is_momo = payment_method in network_map

        flw_config = {
            'public_key':      settings.FLW_PUBLIC_KEY,
            'tx_ref':          tx_ref,
            'amount':          str(order.total_amount),
            'currency':        'GHS',
            'payment_options': 'mobilemoney' if is_momo else 'mobilemoney,card',
            'redirect_url':    request.build_absolute_uri('/checkout/payment/callback/'),
            'customer': {
                'email':        order.customer.email or f"{order.customer.phone}@lynctel.com",
                'phone_number': order.delivery_phone,
                'name':         order.customer.get_full_name() or order.customer.phone,
            },
            'customizations': {
                'title':       'Lynctel',
                'description': f'Payment for {order.order_ref}',
            },
            'meta': {'order_ref': order.order_ref},
        }

        if is_momo and momo_number:
            flw_config['mobile_money'] = {
                'phone':   momo_number,
                'network': network_map[payment_method],
            }

        return render(request, 'payment/pay.html', {
            'order':         order,
            'payment':       payment,
            'flw_config':    json.dumps(flw_config),
            'FLW_PUBLIC_KEY': settings.FLW_PUBLIC_KEY,
            'cart_count':    0,
        })

    return render(request, 'payment/payment.html', {
        'pending_order': pending_order,
        'cart':          cart,
        'cart_count':    cart.total_items,
    })


@login_required
def payment_callback(request):
    """Flutterwave redirects here after payment."""
    status   = request.GET.get('status')
    tx_ref   = request.GET.get('tx_ref')
    trans_id = request.GET.get('transaction_id')

    if not tx_ref:
        messages.error(request, 'Invalid payment response.')
        return redirect('frontend:home')

    try:
        payment = Payment.objects.get(transaction_id=tx_ref)
        order   = payment.order
    except Payment.DoesNotExist:
        messages.error(request, 'Payment record not found.')
        return redirect('frontend:home')

    if status == 'successful' and trans_id:
        verified = _verify_flw_transaction(trans_id, order.total_amount)
        if verified:
            _mark_paid(order, payment, trans_id, {'verified_via': 'callback'})
            messages.success(request, f'Payment confirmed! Order {order.order_ref} is being processed. 🎉')
            return redirect('order:confirmation', order_ref=order.order_ref)
        else:
            payment.status = Payment.Status.FAILED
            payment.save()
            messages.error(request, 'Payment could not be verified. Please contact support.')
    elif status == 'cancelled':
        payment.status = Payment.Status.CANCELLED
        payment.save()
        messages.warning(request, 'Payment was cancelled. Try again when ready.')
    else:
        payment.status = Payment.Status.FAILED
        payment.save()
        messages.error(request, 'Payment failed. Please try a different method.')

    return render(request, 'payment/failed.html', {
        'order':      order,
        'cart_count': 0,
    })


@csrf_exempt
@require_POST
def flutterwave_webhook(request):
    """
    Flutterwave server-to-server webhook.
    Add this URL in your Flutterwave dashboard under Webhooks:
    https://yourdomain.com/checkout/payment/webhook/flutterwave/
    """
    secret_hash = settings.FLW_WEBHOOK_SECRET
    signature   = request.headers.get('verif-hash', '')

    if signature != secret_hash:
        return HttpResponse(status=401)

    try:
        payload = json.loads(request.body)
    except json.JSONDecodeError:
        return HttpResponse(status=400)

    event = payload.get('event')
    data  = payload.get('data', {})

    if event == 'charge.completed' and data.get('status') == 'successful':
        tx_ref   = data.get('tx_ref', '')
        trans_id = str(data.get('id', ''))
        amount   = data.get('amount', 0)

        try:
            payment = Payment.objects.get(transaction_id=tx_ref)
            order   = payment.order
            if payment.status != Payment.Status.SUCCESS:
                if float(amount) >= float(order.total_amount):
                    _mark_paid(order, payment, trans_id, data)
        except Payment.DoesNotExist:
            pass

    return HttpResponse(status=200)


def _verify_flw_transaction(transaction_id, expected_amount):
    """Call Flutterwave to verify a transaction is genuine and matches the amount."""
    try:
        resp = requests.get(
            f"https://api.flutterwave.com/v3/transactions/{transaction_id}/verify",
            headers={
                'Authorization': f'Bearer {settings.FLW_SECRET_KEY}',
                'Content-Type':  'application/json',
            },
            timeout=10,
        )
        d = resp.json()
        return (
            d.get('status') == 'success'
            and d['data']['status'] == 'successful'
            and d['data']['currency'] == 'GHS'
            and float(d['data']['amount']) >= float(expected_amount)
        )
    except Exception:
        return False


def _mark_paid(order, payment, gateway_ref, gateway_data):
    """Mark order and payment as successfully paid."""
    payment.status           = Payment.Status.SUCCESS
    payment.gateway_ref      = gateway_ref
    payment.gateway_response = gateway_data
    payment.paid_at          = timezone.now()
    payment.save()

    order.payment_status = Order.PaymentStatus.PAID
    order.status         = Order.Status.CONFIRMED
    order.save()
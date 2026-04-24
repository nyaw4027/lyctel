import json
import uuid
import requests

from django.shortcuts import render, redirect
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.http import HttpResponse
from django.conf import settings
from django.utils import timezone
from django.db import transaction

from cart.models import Cart
from order.models import Order, OrderItem
from .models import Payment


MOMO_OPTIONS = [
    ('mtn_momo',      'MTN Mobile Money', 'bg-yellow-100 text-yellow-700', 'MTN'),
    ('vodafone_cash', 'Vodafone Cash',    'bg-red-100 text-red-600',       'VDF'),
    ('airteltigo',    'AirtelTigo Money', 'bg-blue-100 text-blue-700',     'ATL'),
]


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

        with transaction.atomic():
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

        tx_ref = f"LYN-{order.order_ref}-{uuid.uuid4().hex[:6].upper()}"
        Payment.objects.create(
            order          = order,
            method         = payment_method,
            amount         = pending_order['total'],
            transaction_id = tx_ref,
            momo_number    = momo_number,
            status         = Payment.Status.PENDING,
        )

        cart.items.all().delete()
        del request.session['pending_order']

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
                'description': f'Order {order.order_ref}',
            },
            'meta': {'order_ref': order.order_ref},
        }
        if is_momo and momo_number:
            flw_config['mobile_money'] = {
                'phone':   momo_number,
                'network': network_map[payment_method],
            }

        return render(request, 'payment/pay.html', {
            'order':          order,
            'flw_config':     json.dumps(flw_config),
            'FLW_PUBLIC_KEY': settings.FLW_PUBLIC_KEY,
            'cart_count':     0,
        })

    # GET — show payment method selection
    return render(request, 'payment/payment.html', {
        'pending_order': pending_order,
        'cart':          cart,
        'cart_count':    cart.total_items,
        'momo_options':  MOMO_OPTIONS,
    })


@login_required
def payment_callback(request):
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
        messages.error(request, 'Payment not found.')
        return redirect('frontend:home')

    if status == 'successful' and trans_id:
        if _verify_flw_transaction(trans_id, order.total_amount):
            _mark_paid(order, payment, trans_id, {'verified_via': 'callback'})
            messages.success(request, f'Payment confirmed! Order {order.order_ref} is being processed.')
            return redirect('order:confirmation', order_ref=order.order_ref)
        payment.status = Payment.Status.FAILED
        payment.save()
        messages.error(request, 'Payment verification failed. Contact support.')
    elif status == 'cancelled':
        payment.status = Payment.Status.CANCELLED
        payment.save()
        messages.warning(request, 'Payment was cancelled.')
    else:
        payment.status = Payment.Status.FAILED
        payment.save()
        messages.error(request, 'Payment failed. Please try again.')

    return render(request, 'payment/failed.html', {'order': order, 'cart_count': 0})


@csrf_exempt
@require_POST
def flutterwave_webhook(request):
    if request.headers.get('verif-hash', '') != settings.FLW_WEBHOOK_SECRET:
        return HttpResponse(status=401)
    try:
        payload = json.loads(request.body)
    except json.JSONDecodeError:
        return HttpResponse(status=400)

    data = payload.get('data', {})
    if payload.get('event') == 'charge.completed' and data.get('status') == 'successful':
        try:
            payment = Payment.objects.get(transaction_id=data.get('tx_ref', ''))
            order   = payment.order
            if payment.status != Payment.Status.SUCCESS:
                if float(data.get('amount', 0)) >= float(order.total_amount):
                    _mark_paid(order, payment, str(data.get('id', '')), data)
        except Payment.DoesNotExist:
            pass

    return HttpResponse(status=200)


def _verify_flw_transaction(transaction_id, expected_amount):
    try:
        resp = requests.get(
            f"https://api.flutterwave.com/v3/transactions/{transaction_id}/verify",
            headers={'Authorization': f'Bearer {settings.FLW_SECRET_KEY}'},
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
    with transaction.atomic():
        payment.status           = Payment.Status.SUCCESS
        payment.gateway_ref      = gateway_ref
        payment.gateway_response = gateway_data
        payment.paid_at          = timezone.now()
        payment.save()

        order.payment_status = Order.PaymentStatus.PAID
        order.status         = Order.Status.CONFIRMED
        order.save()

        _split_commissions(order)


def _split_commissions(order):
    try:
        from vendors.models import VendorEarning, AppCommission
    except ImportError:
        return

    for item in order.items.select_related('product__vendor').all():
        product = item.product
        if not product or not product.vendor:
            continue

        vendor     = product.vendor
        gross      = item.unit_price * item.quantity
        rate       = vendor.commission_rate / 100
        commission = round(gross * rate, 2)
        net_vendor = round(gross - commission, 2)

        AppCommission.objects.create(
            order=order, vendor=vendor,
            amount=commission, rate=vendor.commission_rate,
        )
        VendorEarning.objects.create(
            vendor=vendor, order=order,
            gross_amount=gross, commission=commission,
            net_amount=net_vendor, status='pending',
        )
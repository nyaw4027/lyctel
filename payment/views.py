from django.shortcuts import render, redirect
from django.contrib import messages
from django.contrib.auth.decorators import login_required
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

        # Create the Order record
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
        for cart_item in cart.items.select_related('product').all():
            OrderItem.objects.create(
                order        = order,
                product      = cart_item.product,
                product_name = cart_item.product.name,
                unit_price   = cart_item.product.selling_price,
                quantity     = cart_item.quantity,
            )
            cart_item.product.stock_qty -= cart_item.quantity
            cart_item.product.save()

        # Create payment record
        Payment.objects.create(
            order       = order,
            method      = payment_method,
            amount      = pending_order['total'],
            momo_number = momo_number,
            status      = Payment.Status.PENDING,
        )

        # Clear cart + session
        cart.items.all().delete()
        del request.session['pending_order']

        # TODO Phase 2: trigger Flutterwave / MoMo API here

        messages.success(request, f'Order {order.order_ref} placed! We will confirm your payment shortly.')
        return redirect('order:confirmation', order_ref=order.order_ref)

    return render(request, 'payment/payment.html', {
        'pending_order': pending_order,
        'cart':          cart,
        'cart_count':    cart.total_items,
    })


def flutterwave_webhook(request):
    """
    Placeholder for Phase 2 — Flutterwave will POST here after payment.
    """
    # TODO: verify signature, update Order.payment_status and Payment.status
    return render(request, 'payment/webhook_ack.html', status=200)
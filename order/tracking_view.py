from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from .models import Order


@login_required
def order_tracking(request, order_ref):
    order = get_object_or_404(Order, order_ref=order_ref, customer=request.user)

    try:
        delivery = order.delivery
    except Exception:
        delivery = None

    # Build timeline steps
    all_steps = [
        ('pending',    'Order Placed',       'Your order has been received.'),
        ('confirmed',  'Payment Confirmed',  'Payment verified successfully.'),
        ('processing', 'Being Prepared',     'Your items are being packed.'),
        ('dispatched', 'Out for Delivery',   'A rider is on the way to you.'),
        ('delivered',  'Delivered',          'Your order has been delivered.'),
    ]

    status_order = ['pending', 'confirmed', 'processing', 'dispatched', 'delivered']
    current_idx  = status_order.index(order.status) if order.status in status_order else 0

    steps = []
    for i, (status, label, desc) in enumerate(all_steps):
        if i < current_idx:
            state = 'done'
        elif i == current_idx:
            state = 'active'
        else:
            state = 'pending'
        steps.append({'status': status, 'label': label, 'desc': desc, 'state': state})

    return render(request, 'order/tracking.html', {
        'order':    order,
        'delivery': delivery,
        'steps':    steps,
        'cart_count': 0,
    })
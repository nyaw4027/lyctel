from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from cart.models import Cart, CartItem
from delivery.models import DeliveryZone
from .models import Order, OrderItem


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
def checkout(request):
    cart  = get_or_create_cart(request)
    zones = DeliveryZone.objects.filter(is_active=True)

    if cart.total_items == 0:
        messages.warning(request, 'Your cart is empty.')
        return redirect('cart:detail')

    if request.method == 'POST':
        delivery_address = request.POST.get('delivery_address', '').strip()
        delivery_city    = request.POST.get('delivery_city', '').strip()
        delivery_phone   = request.POST.get('delivery_phone', '').strip()
        zone_id          = request.POST.get('zone_id')

        errors = {}
        if not delivery_address: errors['delivery_address'] = 'Enter your delivery address.'
        if not delivery_city:    errors['delivery_city']    = 'Enter your city.'
        if not delivery_phone:   errors['delivery_phone']   = 'Enter a delivery phone number.'
        if not zone_id:          errors['zone_id']          = 'Select a delivery zone.'

        if errors:
            return render(request, 'order/checkout.html', {
                'cart': cart, 'zones': zones, 'errors': errors,
                'cart_count': cart.total_items, 'form_data': request.POST,
            })

        zone         = get_object_or_404(DeliveryZone, pk=zone_id, is_active=True)
        subtotal     = cart.total_price
        delivery_fee = zone.delivery_fee
        total        = subtotal + delivery_fee

        request.session['pending_order'] = {
            'delivery_address': delivery_address,
            'delivery_city':    delivery_city,
            'delivery_phone':   delivery_phone,
            'zone_id':          zone.pk,
            'subtotal':         str(subtotal),
            'delivery_fee':     str(delivery_fee),
            'total':            str(total),
        }
        return redirect('payment:page')

    return render(request, 'order/checkout.html', {
        'cart':       cart,
        'zones':      zones,
        'cart_count': cart.total_items,
        'user':       request.user,
    })


@login_required
def order_confirmation(request, order_ref):
    order = get_object_or_404(Order, order_ref=order_ref, customer=request.user)
    return render(request, 'order/order_confirmation.html', {
        'order': order, 'cart_count': 0,
    })


@login_required
def order_history(request):
    orders = Order.objects.filter(customer=request.user).order_by('-created_at')
    cart   = get_or_create_cart(request)
    return render(request, 'order/order_history.html', {
        'orders': orders, 'cart_count': cart.total_items,
    })
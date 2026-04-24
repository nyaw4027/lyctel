from decimal import Decimal

from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.contrib.auth.decorators import login_required

from cart.models import Cart
from delivery.models import DeliveryZone

from .models import Order


# -------------------------
# CART HELPER (CLEAN)
# -------------------------
def get_or_create_cart(request):
    if request.user.is_authenticated:
        cart, _ = Cart.objects.get_or_create(user=request.user)
    else:
        if not request.session.session_key:
            request.session.create()
        cart, _ = Cart.objects.get_or_create(
            session_key=request.session.session_key,
            user=None
        )
    return cart


# -------------------------
# CHECKOUT
#
@login_required
def checkout(request):
    cart = get_or_create_cart(request)
    zones = DeliveryZone.objects.filter(is_active=True)

    if cart.total_items == 0:
        messages.warning(request, 'Your cart is empty.')
        return redirect('cart:detail')  # ✅ FIXED NAME

    if request.method == 'POST':
        delivery_address = request.POST.get('delivery_address', '').strip()
        delivery_city    = request.POST.get('delivery_city', '').strip()
        delivery_phone   = request.POST.get('delivery_phone', '').strip()
        zone_id          = request.POST.get('zone_id')

        errors = {}

        if not delivery_address:
            errors['delivery_address'] = 'Enter your delivery address.'
        if not delivery_city:
            errors['delivery_city'] = 'Enter your city.'
        if not delivery_phone:
            errors['delivery_phone'] = 'Enter a delivery phone number.'
        if not zone_id:
            errors['zone_id'] = 'Select a delivery zone.'

        if errors:
            return render(request, 'order/checkout.html', {
                'cart': cart,
                'zones': zones,
                'errors': errors,
                'cart_count': cart.total_items,
                'form_data': request.POST,
            })

        zone = get_object_or_404(DeliveryZone, pk=zone_id, is_active=True)

        subtotal     = Decimal(cart.total_price)
        delivery_fee = Decimal(zone.delivery_fee)
        total        = subtotal + delivery_fee

        # ✅ SAVE TEMP ORDER DATA
        request.session['pending_order'] = {
            'delivery_address': delivery_address,
            'delivery_city': delivery_city,
            'delivery_phone': delivery_phone,
            'zone_id': zone.pk,
            'subtotal': str(subtotal),
            'delivery_fee': str(delivery_fee),
            'total': str(total),
        }

        return redirect('payment:page')

    return render(request, 'order/checkout.html', {
        'cart': cart,
        'zones': zones,
        'cart_count': cart.total_items,
        'user': request.user,
    })


# -------------------------
# ORDER CONFIRMATION
# -------------------------
@login_required
def order_confirmation(request, order_ref):
    order = get_object_or_404(
        Order,
        order_ref=order_ref,
        customer=request.user
    )

    # security check
    if order.payment_status != Order.PaymentStatus.PAID:
        return render(request, 'order/not_paid.html', {
            'order': order,
            'cart_count': 0
        })

    items = order.items.select_related('product')

    return render(request, 'order/order_confirmation.html', {
        'order': order,
        'items': items,
        'cart_count': 0,
    })


# -------------------------
# ORDER HISTORY
# -------------------------
@login_required
def order_history(request):
    orders = Order.objects.filter(
        customer=request.user
    ).prefetch_related('items').order_by('-created_at')

    cart = get_or_create_cart(request)

    return render(request, 'order/order_history.html', {
        'orders': orders,
        'cart_count': cart.total_items,
    })




from delivery.models import Delivery, DeliveryZone
from delivery.services import assign_nearest_rider

def create_delivery_for_order(order):
    zone = DeliveryZone.objects.filter(is_active=True).first()

    delivery = Delivery.objects.create(
        order=order,
        zone=zone,
        pickup_location="Vendor Location",
        dropoff_location=order.address,
        pickup_lat=order.vendor_lat,
        pickup_lng=order.vendor_lng,
        dropoff_lat=order.lat,
        dropoff_lng=order.lng,
        status=Delivery.Status.PENDING
    )

    # 🚀 AUTO ASSIGN RIDER
    rider = assign_nearest_rider(delivery)

    if not rider:
        # fallback: retry later system
        from delivery.tasks import try_reassign_later
        try_reassign_later(delivery)

    return delivery




from decimal import Decimal
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.utils import timezone

from cart.models import Cart
from delivery.models import Delivery, DeliveryZone
from delivery.services import assign_rider_to_delivery
from .models import Order


# ── CART HELPER ───────────────────────────────────────────

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


# ── CHECKOUT ──────────────────────────────────────────────

@login_required
def checkout(request):
    cart  = get_or_create_cart(request)
    zones = DeliveryZone.objects.filter(is_active=True)

    if cart.total_items == 0:
        messages.warning(request, 'Your cart is empty.')
        return redirect('cart:detail')

    if request.method == 'POST':
        delivery_choice        = request.POST.get('delivery_choice', 'rider')
        delivery_phone         = request.POST.get('delivery_phone', '').strip()
        delivery_address       = request.POST.get('delivery_address', '').strip()
        delivery_city          = request.POST.get('delivery_city', '').strip()
        zone_id                = request.POST.get('zone_id', '').strip()
        special_notes          = request.POST.get('special_notes', '').strip()
        parcel_bus_station     = request.POST.get('parcel_bus_station', '').strip()
        parcel_recipient_phone = request.POST.get('parcel_recipient_phone', '').strip()
        parcel_notes           = request.POST.get('parcel_notes', '').strip()

        errors = {}

        # Phone is required for all modes
        if not delivery_phone:
            errors['delivery_phone'] = 'Enter a contact phone number.'

        if delivery_choice == 'rider':
            if not delivery_address:
                errors['delivery_address'] = 'Enter your delivery address.'
            if not delivery_city:
                errors['delivery_city'] = 'Enter your city.'
            if not zone_id:
                errors['zone_id'] = 'Select a delivery zone.'

        elif delivery_choice == 'parcel':
            if not parcel_bus_station:
                errors['parcel_bus_station'] = 'Enter the bus station name.'
            if not parcel_recipient_phone:
                errors['parcel_recipient_phone'] = 'Enter the recipient phone number at the station.'

        # pickup needs nothing extra — vendor location is already known

        if errors:
            return render(request, 'order/checkout.html', {
                'cart':       cart,
                'zones':      zones,
                'errors':     errors,
                'cart_count': cart.total_items,
                'form_data':  request.POST,
            })

        # ── Calculate fee ──────────────────────────────────
        subtotal = Decimal(cart.total_price)

        if delivery_choice == 'rider':
            zone         = get_object_or_404(DeliveryZone, pk=zone_id, is_active=True)
            delivery_fee = Decimal(zone.delivery_fee)
            zone_pk      = zone.pk
        else:
            # pickup and parcel have no platform delivery fee
            delivery_fee = Decimal('0.00')
            zone_pk      = None

        total = subtotal + delivery_fee

        # ── Store in session for payment view ──────────────
        request.session['pending_order'] = {
            'delivery_choice':        delivery_choice,
            'delivery_address':       delivery_address,
            'delivery_city':          delivery_city,
            'delivery_phone':         delivery_phone,
            'zone_id':                zone_pk,
            'subtotal':               str(subtotal),
            'delivery_fee':           str(delivery_fee),
            'total':                  str(total),
            'special_notes':          special_notes,
            'parcel_bus_station':     parcel_bus_station,
            'parcel_recipient_phone': parcel_recipient_phone,
            'parcel_notes':           parcel_notes,
        }

        return redirect('payment:page')

    return render(request, 'order/checkout.html', {
        'cart':       cart,
        'zones':      zones,
        'cart_count': cart.total_items,
        'user':       request.user,
    })


# ── ORDER CONFIRMATION ────────────────────────────────────

@login_required
def order_confirmation(request, order_ref):
    order = get_object_or_404(Order, order_ref=order_ref, customer=request.user)

    if order.payment_status != Order.PaymentStatus.PAID:
        return render(request, 'order/not_paid.html', {
            'order':      order,
            'cart_count': 0,
        })

    items = order.items.select_related('product')

    return render(request, 'order/order_confirmation.html', {
        'order':      order,
        'items':      items,
        'cart_count': 0,
    })


# ── ORDER HISTORY ─────────────────────────────────────────

@login_required
def order_history(request):
    orders = Order.objects.filter(
        customer=request.user
    ).prefetch_related('items').order_by('-created_at')

    cart = get_or_create_cart(request)

    return render(request, 'order/order_history.html', {
        'orders':     orders,
        'cart_count': cart.total_items,
    })


# ── ORDER TRACKING ────────────────────────────────────────

@login_required
def order_tracking(request, order_ref):
    order    = get_object_or_404(Order, order_ref=order_ref, customer=request.user)
    delivery = getattr(order, 'delivery', None)

    return render(request, 'order/tracking.html', {
        'order':      order,
        'delivery':   delivery,
        'cart_count': 0,
    })


# ── VENDOR: CONFIRM PICKUP ────────────────────────────────

@login_required
def vendor_confirm_pickup(request, order_ref):
    """Vendor marks a pickup order as ready for collection."""
    from vendors.models import Vendor

    if request.method != 'POST':
        return redirect('vendors:dashboard')

    try:
        vendor = request.user.vendor
    except Exception:
        messages.error(request, 'Vendor account not found.')
        return redirect('vendors:dashboard')

    order = get_object_or_404(
        Order,
        order_ref=order_ref,
        items__product__vendor=vendor,
        delivery_choice='pickup',
    )

    order.pickup_confirmed_at = timezone.now()
    order.status = Order.Status.READY
    order.save(update_fields=['pickup_confirmed_at', 'status'])

    # Notify customer (plug in your notification system here)
    _notify_customer(
        order.customer,
        title=f'Order {order.order_ref} Ready for Pickup',
        body=(
            f'Your order from {vendor.shop_name} is ready to collect. '
            f'Head to: {vendor.location or vendor.phone}.'
        ),
    )

    messages.success(request, f'Order {order.order_ref} marked as ready for pickup.')
    return redirect('vendors:dashboard')


# ── VENDOR: DISPATCH PARCEL ───────────────────────────────

@login_required
def vendor_dispatch_parcel(request, order_ref):
    """Vendor confirms a parcel has been sent via bus."""
    from vendors.models import Vendor

    if request.method != 'POST':
        return redirect('vendors:dashboard')

    try:
        vendor = request.user.vendor
    except Exception:
        messages.error(request, 'Vendor account not found.')
        return redirect('vendors:dashboard')

    order = get_object_or_404(
        Order,
        order_ref=order_ref,
        items__product__vendor=vendor,
        delivery_choice='parcel',
    )

    waybill = request.POST.get('parcel_waybill', '').strip()

    order.parcel_dispatched_at = timezone.now()
    order.parcel_waybill       = waybill
    order.status               = Order.Status.DISPATCHED
    order.save(update_fields=['parcel_dispatched_at', 'parcel_waybill', 'status'])

    waybill_line = f' Waybill: {waybill}.' if waybill else ''
    _notify_customer(
        order.customer,
        title=f'Order {order.order_ref} Dispatched via Bus',
        body=(
            f'Your order from {vendor.shop_name} has been sent to '
            f'{order.parcel_bus_station}.{waybill_line} '
            f'Call {order.parcel_recipient_phone} to arrange collection.'
        ),
    )

    messages.success(
        request,
        f'Order {order.order_ref} marked as dispatched.'
        + (f' Waybill: {waybill}.' if waybill else ''),
    )
    return redirect('vendors:dashboard')


# ── INTERNAL: customer notification stub ──────────────────

def _notify_customer(user, title, body):
    """
    Replace this with your real notification call —
    e.g. Notification.objects.create(...) or send_sms(...).
    """
    if not user:
        return
    try:
        from chat.models import Notification  # adjust import to your app
        Notification.objects.create(user=user, title=title, body=body)
    except Exception:
        pass  # fail silently — don't break the order flow


# ── DELIVERY HELPER (kept from original) ─────────────────

def create_delivery_for_order(order):
    """Only called for rider-mode orders."""
    from delivery.models import Delivery, DeliveryZone

    zone = DeliveryZone.objects.filter(is_active=True).first()

    delivery = Delivery.objects.create(
        order=order,
        zone=zone,
        pickup_location='Vendor Location',
        dropoff_location=order.delivery_address,
        status=Delivery.Status.PENDING,
    )

    rider = assign_rider_to_delivery(delivery)
    if not rider:
        print(f'[order {order.order_ref}] No available rider found.')

    return delivery
from decimal import Decimal
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.utils import timezone

from cart.models import Cart
from delivery.models import Delivery, DeliveryZone
from delivery.services import assign_rider_to_delivery
from .models import Order

import json
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.contrib.auth.decorators import login_required
from delivery.services import estimate_fee_for_request, ACCRA_CENTER
 
 


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



 
@login_required
def estimate_delivery_fee(request):
    """
    AJAX endpoint called from checkout when customer shares their location.
    POST body: { dropoff_lat, dropoff_lng, vendor_id (optional) }
    Returns: { distance_km, delivery_fee, fee_display }
    """
    try:
        data        = json.loads(request.body)
        dropoff_lat = float(data.get('dropoff_lat', 0))
        dropoff_lng = float(data.get('dropoff_lng', 0))
        vendor_id   = data.get('vendor_id')
 
        if not dropoff_lat or not dropoff_lng:
            return JsonResponse({'error': 'Missing coordinates.'}, status=400)
 
        # Get pickup coords from vendor if provided
        pickup_lat = pickup_lng = None
        if vendor_id:
            try:
                from vendors.models import Vendor
                vendor     = Vendor.objects.get(pk=vendor_id)
                pickup_lat = getattr(vendor, 'latitude',  None)
                pickup_lng = getattr(vendor, 'longitude', None)
            except Exception:
                pass
 
        pickup_lat = pickup_lat or ACCRA_CENTER[0]
        pickup_lng = pickup_lng or ACCRA_CENTER[1]
 
        distance_km, fee = estimate_fee_for_request(
            pickup_lat, pickup_lng, dropoff_lat, dropoff_lng
        )
 
        return JsonResponse({
            'distance_km':  distance_km,
            'delivery_fee': float(fee),
            'fee_display':  f'GHS {fee}',
            'distance_display': f'{distance_km} km',
        })
 
    except (ValueError, TypeError) as e:
        return JsonResponse({'error': str(e)}, status=400)
    



from decimal import Decimal
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.contrib.auth.decorators import login_required

# --- Add these REST Framework imports ---
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
#from .serializers import OrderSerializer 
# ----------------------------------------

from cart.models import Cart
from delivery.models import Delivery, DeliveryZone
from delivery.services import assign_rider_to_delivery
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
        # FIXED: the checkout form has a "Special Notes" textarea
        # (name="special_notes") that was never read here — anything the
        # customer typed (gate colour, landmark, delivery timing) was
        # silently discarded instead of reaching the order.
        special_notes    = request.POST.get('special_notes', '').strip()

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

        # FIXED: a malformed/tampered zone_id (non-numeric) previously
        # raised an unhandled ValueError inside get_object_or_404 — a 500
        # error instead of a friendly "select a valid zone" message.
        try:
            zone = get_object_or_404(DeliveryZone, pk=zone_id, is_active=True)
        except (ValueError, TypeError):
            errors['zone_id'] = 'Select a valid delivery zone.'
            return render(request, 'order/checkout.html', {
                'cart': cart,
                'zones': zones,
                'errors': errors,
                'cart_count': cart.total_items,
                'form_data': request.POST,
            })

        # FIXED: Decimal(<float>) bakes in binary floating-point noise
        # (e.g. Decimal(19.99) becomes Decimal('19.9899999999999984...')).
        # Routing through str() first gives the exact decimal value —
        # important here since this number becomes the amount charged.
        subtotal     = Decimal(str(cart.total_price))
        delivery_fee = Decimal(str(zone.delivery_fee))
        total        = subtotal + delivery_fee

        # ✅ SAVE TEMP ORDER DATA
        request.session['pending_order'] = {
            'delivery_address': delivery_address,
            'delivery_city': delivery_city,
            'delivery_phone': delivery_phone,
            'customer_note': special_notes,
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


# -------------------------
# DELIVERY CREATION (post-payment)
# -------------------------
# FIXED (partial): previously referenced order.address, order.vendor_lat,
# order.vendor_lng, order.lat, and order.lng — NONE of these exist on the
# Order model (which only has delivery_address, delivery_city,
# delivery_phone). This function would crash with AttributeError on its
# very first real call.
#
# STILL UNRESOLVED — needs your input:
#   1. There is no lat/lng anywhere in the checkout flow at all. To populate
#      pickup_lat/pickup_lng/dropoff_lat/dropoff_lng for real, we need
#      either a geocoding step (address -> coordinates) or stored
#      coordinates on Vendor/DeliveryZone. I don't have delivery/models.py
#      yet, so I don't know whether these fields are required (NOT NULL)
#      on the Delivery model, which determines whether passing None here
#      is even safe.
#   2. pickup_location is hardcoded to the literal string "Vendor
#      Location" rather than the actual vendor's address — and since an
#      order can contain items from MULTIPLE vendors, "one pickup point
#      per order" may not even be the right model for a marketplace like
#      this. Flagging rather than guessing at a fix.
def create_delivery_for_order(order):
    zone = DeliveryZone.objects.filter(is_active=True).first()

    delivery = Delivery.objects.create(
        order=order,
        zone=zone,
        pickup_location="Vendor Location",         # TODO: use the real vendor address (see note above)
        dropoff_location=order.delivery_address,    # FIXED: was order.address (doesn't exist)
        pickup_lat=None,                            # TODO: needs a real coordinate source — see note above
        pickup_lng=None,
        dropoff_lat=None,
        dropoff_lng=None,
        status=Delivery.Status.PENDING
    )

    rider = assign_rider_to_delivery(delivery)

    if not rider:
        print("No available rider found.")

    return delivery


# -------------------------
# ORDER TRACKING (The missing function!)
# -------------------------
@login_required
def order_tracking(request, order_ref):
    order = get_object_or_404(
        Order, 
        order_ref=order_ref, 
        customer=request.user
    )
    
    # If you have a delivery linked to this order, get it
    delivery = getattr(order, 'delivery', None)
    
    return render(request, 'order/tracking.html', {
        'order': order,
        'delivery': delivery,
        'cart_count': 0, # Usually 0 since order is already placed
    })


@login_required
def order_receipt(request, order_ref):
    """Download a PDF receipt for a paid order."""
    order = get_object_or_404(
        Order,
        order_ref=order_ref,
        customer=request.user,
        payment_status=Order.PaymentStatus.PAID,
    )
    from .pdf import generate_order_receipt_pdf
    return generate_order_receipt_pdf(order)


#@api_view(['GET'])
#@permission_classes([IsAuthenticated])
#def api_order_history(request):
    #orders = Order.objects.filter(customer=request.user).order_by('-created_at')
   # serializer = OrderSerializer(orders, many=True)
    #return Response(serializer.data)

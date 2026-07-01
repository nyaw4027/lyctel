import json
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from cart.models import Cart
from delivery.models import Delivery
from delivery.services import ACCRA_CENTER, assign_rider_to_delivery, estimate_fee_for_request

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


# ── CHECKOUT ───────────────────────────────────────────────

@login_required
def checkout(request):
    cart = get_or_create_cart(request)

    if cart.total_items == 0:
        messages.warning(request, "Your cart is empty.")
        return redirect("cart:detail")

    if request.method == "POST":
        delivery_choice        = request.POST.get("delivery_choice", "rider")
        delivery_phone         = request.POST.get("delivery_phone", "").strip()
        delivery_address       = request.POST.get("delivery_address", "").strip()
        delivery_city           = request.POST.get("delivery_city", "").strip()
        # FIXED: checkout.html posts this field as "order_note", not
        # "special_notes" — the old code was silently discarding every note.
        order_note              = request.POST.get("order_note", "").strip()
        parcel_bus_station       = request.POST.get("parcel_bus_station", "").strip()
        parcel_recipient_phone  = request.POST.get("parcel_recipient_phone", "").strip()
        parcel_notes            = request.POST.get("parcel_notes", "").strip()

        # FIXED: the map in checkout.html writes to hidden inputs
        # delivery_lat / delivery_lng, but nothing ever read them —
        # coordinates picked on the frontend never reached the backend.
        dlat_raw = request.POST.get("delivery_lat", "").strip()
        dlng_raw = request.POST.get("delivery_lng", "").strip()

        errors = {}

        # Phone is required for all delivery methods
        if not delivery_phone:
            errors["delivery_phone"] = "Enter a contact phone number."

        if delivery_choice == "rider":
            if not delivery_address:
                errors["delivery_address"] = "Enter your delivery address."
            if not delivery_city:
                errors["delivery_city"] = "Enter your city."

        elif delivery_choice == "parcel":
            if not parcel_bus_station:
                errors["parcel_bus_station"] = "Enter the bus station name."
            if not parcel_recipient_phone:
                errors["parcel_recipient_phone"] = "Enter the recipient phone number."

        if errors:
            return render(request, "order/checkout.html", {
                "cart": cart,
                "errors": errors,
                "cart_count": cart.total_items,
                "form_data": request.POST,
            })

        # Cart subtotal
        subtotal = Decimal(str(cart.total_price))

        # Delivery fee — never trust the client-posted number, recompute
        # server-side from coordinates whenever we have them.
        delivery_lat = delivery_lng = None
        distance_km  = None
        delivery_fee = Decimal("0.00")

        if delivery_choice == "rider" and dlat_raw and dlng_raw:
            try:
                delivery_lat = float(dlat_raw)
                delivery_lng = float(dlng_raw)
                # No per-vendor pickup point is chosen at cart-checkout time
                # (a cart can span multiple vendors), so we estimate from a
                # fixed city-center pickup, same fallback used by the
                # estimate_delivery_fee AJAX endpoint below.
                distance_km, fee = estimate_fee_for_request(
                    ACCRA_CENTER[0], ACCRA_CENTER[1], delivery_lat, delivery_lng
                )
                delivery_fee = Decimal(str(fee))
            except (TypeError, ValueError):
                delivery_lat = delivery_lng = distance_km = None
                delivery_fee = Decimal("0.00")

        total = subtotal + delivery_fee

        # Save order until payment succeeds
        request.session["pending_order"] = {
            "delivery_choice": delivery_choice,
            "delivery_address": delivery_address,
            "delivery_city": delivery_city,
            "delivery_phone": delivery_phone,
            "delivery_lat": delivery_lat,
            "delivery_lng": delivery_lng,
            "distance_km": distance_km,
            "subtotal": str(subtotal),
            "delivery_fee": str(delivery_fee),
            "total": str(total),
            "order_note": order_note,
            "parcel_bus_station": parcel_bus_station,
            "parcel_recipient_phone": parcel_recipient_phone,
            "parcel_notes": parcel_notes,
        }

        return redirect("payment:page")

    return render(request, "order/checkout.html", {
        "cart": cart,
        "cart_count": cart.total_items,
        "user": request.user,
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


# ── ORDER RECEIPT ─────────────────────────────────────────

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


# ── VENDOR: CONFIRM PICKUP ────────────────────────────────

@login_required
def vendor_confirm_pickup(request, order_ref):
    """Vendor marks a pickup order as ready for collection."""
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


# ── DELIVERY CREATION (post-payment) ──────────────────────
#
# NOTE: previous versions of this function referenced order.address,
# order.vendor_lat/vendor_lng, and order.lat/lng — none of which are
# guaranteed to exist on the Order model. Using getattr(..., None) below
# avoids a hard crash either way, but this is still a TODO:
#   1. There's no per-vendor pickup coordinate anywhere in checkout yet
#      (a cart can span multiple vendors), so pickup_lat/pickup_lng will
#      be None until that's designed properly.
#   2. dropoff coordinates are only available if the Order model actually
#      stores delivery_lat/delivery_lng (populated from the session
#      "pending_order" dict set in checkout() above, once payment succeeds
#      and the real Order row is created). Confirm those fields exist on
#      Order before relying on them.
def create_delivery_for_order(order):
    """Only called for rider-mode orders."""
    from delivery.models import DeliveryZone

    zone = DeliveryZone.objects.filter(is_active=True).first()

    delivery = Delivery.objects.create(
        order=order,
        zone=zone,
        pickup_location='Vendor Location',  # TODO: use real vendor address — see note above
        dropoff_location=order.delivery_address,
        pickup_lat=getattr(order, 'vendor_lat', None),
        pickup_lng=getattr(order, 'vendor_lng', None),
        dropoff_lat=getattr(order, 'delivery_lat', None),
        dropoff_lng=getattr(order, 'delivery_lng', None),
        status=Delivery.Status.PENDING,
    )

    rider = assign_rider_to_delivery(delivery)
    if not rider:
        print(f'[order {order.order_ref}] No available rider found.')

    return delivery


# ── FEE ESTIMATE (AJAX, called from checkout map) ─────────

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
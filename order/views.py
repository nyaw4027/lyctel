import json
import logging
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from cart.models import Cart
from delivery.models import Delivery
from delivery.services import ACCRA_CENTER, assign_rider_to_delivery, estimate_fee_for_request

from .models import Order, OrderDispute

logger = logging.getLogger(__name__)

# ── CART HELPER ───────────────────────────────────────────


def _cget(key, default=None):
    try:
        from django.core.cache import cache
        return _cget(key, default)
    except Exception:
        return default

def _cset(key, val, ttl):
    try:
        from django.core.cache import cache
        _cset(key, val, ttl)
    except Exception:
        pass


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
            from django.conf import settings as _s
            return render(request, "order/checkout.html", {
                "cart":           cart,
                "errors":         errors,
                "cart_count":     cart.total_items,
                "form_data":      request.POST,
                "locationiq_key": getattr(_s, 'LOCATIONIQ_API_KEY', ''),
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
                # Server-side recalculation — never trust the client value.
                # This prevents fee manipulation from browser devtools.
                distance_km, fee = estimate_fee_for_request(
                    ACCRA_CENTER[0], ACCRA_CENTER[1], delivery_lat, delivery_lng
                )
                delivery_fee = Decimal(str(fee))
            except (TypeError, ValueError):
                # Service unavailable — fall back to the frontend-calculated
                # fee that was posted in the hidden delivery_fee field.
                submitted_fee = request.POST.get("delivery_fee", "0").strip()
                try:
                    delivery_fee = max(Decimal("0.00"), Decimal(submitted_fee))
                except Exception:
                    delivery_fee = Decimal("0.00")
                delivery_lat = float(dlat_raw) if dlat_raw else None
                delivery_lng = float(dlng_raw) if dlng_raw else None
                distance_km  = None

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

    from django.conf import settings as _s
    return render(request, "order/checkout.html", {
        "cart":           cart,
        "cart_count":     cart.total_items,
        "user":           request.user,
        # Required by checkout map — used for LocationIQ tiles + geocoding
        "locationiq_key": getattr(_s, 'LOCATIONIQ_API_KEY', ''),
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
    AJAX endpoint — supports both:
      GET  /order/estimate-fee/?olat=...&olng=...&dlat=...&dlng=...
      POST /order/estimate-fee/  { dropoff_lat, dropoff_lng, vendor_id }

    checkout.html calls GET /delivery/price/ which maps to
    delivery.views.price_estimate — keep this POST endpoint for
    programmatic use from other views.
    """
    try:
        if request.method == 'GET':
            olat       = float(request.GET.get('olat', ACCRA_CENTER[0]))
            olng       = float(request.GET.get('olng', ACCRA_CENTER[1]))
            dlat       = float(request.GET.get('dlat', 0))
            dlng       = float(request.GET.get('dlng', 0))
            vendor_id  = request.GET.get('vendor_id')
        else:
            data      = json.loads(request.body)
            dlat      = float(data.get('dropoff_lat', 0))
            dlng      = float(data.get('dropoff_lng', 0))
            olat      = ACCRA_CENTER[0]
            olng      = ACCRA_CENTER[1]
            vendor_id = data.get('vendor_id')

        if not dlat or not dlng:
            return JsonResponse({'success': False, 'error': 'Missing coordinates.'}, status=400)

        # Use vendor pickup point if provided
        if vendor_id:
            try:
                from vendors.models import Vendor
                v    = Vendor.objects.get(pk=vendor_id)
                olat = getattr(v, 'latitude',  None) or olat
                olng = getattr(v, 'longitude', None) or olng
            except Exception:
                pass

        distance_km, fee = estimate_fee_for_request(olat, olng, dlat, dlng)
        eta_minutes = max(10, int(float(distance_km) * 3))

        return JsonResponse({
            'success':      True,
            'fee':          str(fee),
            'distance_km':  distance_km,
            'eta_minutes':  eta_minutes,
            # Legacy keys kept for backward compat
            'delivery_fee': float(fee),
            'fee_display':  f'GHS {fee}',
            'distance_display': f'{distance_km} km',
        })

    except (ValueError, TypeError) as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)



@login_required
def open_dispute(request, order_ref):
    order = get_object_or_404(
        Order, order_ref=order_ref, customer=request.user
    )
 
    # Only paid orders can be disputed
    if not order.is_paid:
        messages.error(request, 'Only paid orders can be disputed.')
        return redirect('order:history')
 
    # One dispute per order
    if hasattr(order, 'dispute'):
        messages.info(request, 'A dispute is already open for this order.')
        return redirect('order:dispute_detail', order_ref=order_ref)
 
    if request.method == 'POST':
        reason           = request.POST.get('reason', '')
        description      = request.POST.get('description', '').strip()
        refund_requested = request.POST.get('refund_requested') == '1'
        evidence         = request.FILES.get('evidence')
 
        if not reason or not description:
            messages.error(request, 'Please select a reason and describe the issue.')
        elif len(description) < 20:
            messages.error(request, 'Please describe the issue in more detail (at least 20 characters).')
        else:
            dispute = OrderDispute.objects.create(
                order            = order,
                customer         = request.user,
                reason           = reason,
                description      = description,
                refund_requested = refund_requested,
                evidence         = evidence,
            )
            # Notify staff via SMS
            try:
                from notifications.sms import send_sms
                from django.conf import settings
                admin_phone = getattr(settings, 'ADMIN_PHONE', '')
                if admin_phone:
                    send_sms(
                        admin_phone,
                        f'Lynctel: New dispute opened on order {order.order_ref} '
                        f'by {request.user.display_name}. Reason: {dispute.get_reason_display()}'
                    )
            except Exception:
                pass
 
            messages.success(
                request,
                'Your dispute has been submitted. Our team will review it within 24 hours.'
            )
            return redirect('order:dispute_detail', order_ref=order_ref)
 
    return render(request, 'order/open_dispute.html', {
        'order':   order,
        'reasons': OrderDispute.Reason.choices,
    })
 
 
# ── Customer: view dispute status ─────────────────────────────────────────────
 
@login_required
def dispute_detail(request, order_ref):
    order   = get_object_or_404(Order, order_ref=order_ref, customer=request.user)
    dispute = get_object_or_404(OrderDispute, order=order)
    return render(request, 'order/dispute_detail.html', {
        'order':   order,
        'dispute': dispute,
    })
 
 
# ── Vendor: respond to dispute ────────────────────────────────────────────────
 
@login_required
@require_POST
def vendor_respond_dispute(request, dispute_id):
    dispute = get_object_or_404(OrderDispute, id=dispute_id)
 
    # Verify this vendor owns the order
    vendor = getattr(request.user, 'vendor', None)
    if not vendor:
        messages.error(request, 'Vendor access required.')
        return redirect('vendors:dashboard')
 
    order_items = dispute.order.items.filter(product__vendor=vendor)
    if not order_items.exists():
        messages.error(request, 'Permission denied.')
        return redirect('vendors:dashboard')
 
    response = request.POST.get('vendor_response', '').strip()
    if response:
        dispute.vendor_response    = response
        dispute.vendor_responded_at = timezone.now()
        if dispute.status == OrderDispute.Status.OPEN:
            dispute.status = OrderDispute.Status.REVIEWING
        dispute.save(update_fields=['vendor_response', 'vendor_responded_at', 'status'])
        messages.success(request, 'Your response has been submitted.')
    return redirect('vendors:dashboard')
 
 
# ── Staff: mediation page ─────────────────────────────────────────────────────
 
@login_required
def staff_dispute_list(request):
    if not (request.user.is_staff or request.user.role in ('admin', 'staff')):
        return redirect('frontend:home')
 
    disputes = (
        OrderDispute.objects
        .select_related('order', 'customer', 'assigned_to')
        .prefetch_related('order__items__product__vendor')
        .order_by('status', '-created_at')
    )
 
    status_filter = request.GET.get('status', '')
    if status_filter:
        disputes = disputes.filter(status=status_filter)
 
    return render(request, 'order/staff_disputes.html', {
        'disputes':       disputes,
        'status_choices': OrderDispute.Status.choices,
        'status_filter':  status_filter,
    })
 
 
@login_required
@require_POST
def staff_resolve_dispute(request, dispute_id):
    if not (request.user.is_staff or request.user.role in ('admin', 'staff')):
        return redirect('frontend:home')
 
    dispute    = get_object_or_404(OrderDispute, id=dispute_id)
    action     = request.POST.get('action', '')
    resolution = request.POST.get('resolution', '').strip()
    staff_notes = request.POST.get('staff_notes', '').strip()
 
    dispute.staff_notes  = staff_notes
    dispute.resolution   = resolution
    dispute.assigned_to  = request.user
 
    if action == 'approve_refund':
        dispute.status      = OrderDispute.Status.RESOLVED
        dispute.resolved_at = timezone.now()
        # Update order status
        dispute.order.status         = Order.Status.REFUNDED
        dispute.order.payment_status = Order.PaymentStatus.REFUNDED
        dispute.order.save(update_fields=['status', 'payment_status'])
        # Notify customer
        try:
            from notifications.sms import send_sms
            send_sms(
                dispute.customer.phone,
                f'Lynctel: Your dispute for order {dispute.order.order_ref} '
                f'has been resolved. Refund approved. '
                f'{resolution}'
            )
        except Exception:
            pass
        messages.success(request, 'Dispute resolved — refund approved.')
 
    elif action == 'close':
        dispute.status      = OrderDispute.Status.CLOSED
        dispute.resolved_at = timezone.now()
        try:
            from notifications.sms import send_sms
            send_sms(
                dispute.customer.phone,
                f'Lynctel: Your dispute for order {dispute.order.order_ref} '
                f'has been reviewed and closed. {resolution}'
            )
        except Exception:
            pass
        messages.success(request, 'Dispute closed.')
 
    dispute.save()
    return redirect('order:staff_disputes')


 
@login_required
@require_POST
def reorder(request, order_ref):
    """
    POST /orders/<order_ref>/reorder/
    Adds all items from a past order back into the customer's current cart.
    Only adds items that are still active and in stock.
    """
    from .models import Order
    from cart.models import Cart, CartItem
 
    order = get_object_or_404(
        Order.objects.prefetch_related('items__product'),
        order_ref=order_ref,
        customer=request.user
    )
 
    # Get or create cart
    if request.user.is_authenticated:
        cart, _ = Cart.objects.get_or_create(user=request.user)
    else:
        return redirect('accounts:login')
 
    added    = 0
    skipped  = 0
 
    for item in order.items.all():
        product = item.product
        if not product or product.status != 'active':
            skipped += 1
            continue
 
        cart_item, created = CartItem.objects.get_or_create(
            cart=cart, product=product
        )
        if created:
            cart_item.quantity = item.quantity
        else:
            cart_item.quantity += item.quantity
        cart_item.save()
        added += 1
 
    # Update cart timestamp
    from django.utils import timezone
    cart.updated_at = timezone.now()
    cart.save(update_fields=['updated_at'])
 
    if added:
        msg = f'✓ {added} item{"s" if added > 1 else ""} added to your cart'
        if skipped:
            msg += f' ({skipped} unavailable item{"s" if skipped > 1 else ""} skipped)'
        messages.success(request, msg)
    else:
        messages.warning(request, 'None of the items from this order are currently available.')
 
    # Return JSON for AJAX or redirect for normal request
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'success': True, 'added': added, 'skipped': skipped,
                             'cart_count': cart.total_items})
    return redirect('cart:detail')
 
 
# ── Also Bought ────────────────────────────────────────────────────────────────
 
def also_bought(request, product_id):
    """
    GET /products/<id>/also-bought/
    Returns products frequently bought together with the given product.
    Uses co-purchase data from paid OrderItems.
    Cached for 1 hour.
    """
    from django.core.cache import cache
    from products.models import Product
    from .models import OrderItem
 
    cache_key = f'also_bought:{product_id}'
    cached    = _cget(cache_key)
    if cached is not None:
        return JsonResponse({'products': cached})
 
    try:
        product = get_object_or_404(Product, pk=product_id, status='active')
 
        # Step 1: orders that contain this product (paid only)
        order_ids = (
            OrderItem.objects
            .filter(product=product, order__payment_status='paid')
            .values_list('order_id', flat=True)
        )
 
        # Step 2: other products in those orders, ranked by co-occurrence
        related = (
            OrderItem.objects
            .filter(order_id__in=order_ids, order__payment_status='paid')
            .exclude(product=product)
            .exclude(product__isnull=True)
            .values('product')
            .annotate(count=Count('product'))
            .order_by('-count')[:8]
        )
 
        product_ids = [r['product'] for r in related]
        products    = (
            Product.objects
            .filter(pk__in=product_ids, status='active')
            .prefetch_related('images')
            .select_related('vendor')
        )
        product_map = {p.pk: p for p in products}
 
        result = []
        for pk in product_ids:
            p = product_map.get(pk)
            if not p:
                continue
            img = p.images.first()
            result.append({
                'id':    p.pk,
                'name':  p.name,
                'price': str(p.final_price),
                'url':   f'/products/{p.slug}/',
                'image': img.image.url if img else '',
                'vendor': p.vendor.shop_name if p.vendor else '',
            })
 
        _cset(cache_key, result, 3600)   # 1 hour
        return JsonResponse({'products': result})
 
    except Exception as e:
        logger.error('also_bought error for product %s: %s', product_id, e)
        return JsonResponse({'products': []})
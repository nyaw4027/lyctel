import math
import json
from decimal import Decimal

from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
from django.db.models import Q

from .models import (
    FoodVendor, FoodCategory, FoodItem,
    FoodOrder, FoodOrderItem, FoodCart, FoodCartItem,
)
from delivery.models import Delivery, DeliveryZone


# ─────────────────────────────
# PRICING ENGINE (Uber-style)
# ─────────────────────────────
BASE_FARE    = Decimal('5.00')   # Base fare in GHS
PER_KM_RATE  = Decimal('2.50')   # GHS per km
MIN_FARE     = Decimal('8.00')   # Minimum delivery fee
SURGE_FACTOR = Decimal('1.0')    # Can be bumped to 1.5 during peak hours

def calculate_delivery_fee(distance_km):
    """Uber-style dynamic pricing based on distance."""
    if not distance_km or distance_km <= 0:
        return MIN_FARE
    fee = BASE_FARE + (Decimal(str(distance_km)) * PER_KM_RATE * SURGE_FACTOR)
    return max(fee, MIN_FARE).quantize(Decimal('0.01'))

def haversine_distance(lat1, lng1, lat2, lng2):
    """Straight-line distance between two GPS points in km."""
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) *
         math.cos(math.radians(lat2)) *
         math.sin(dlng / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

def estimate_eta(distance_km, prep_time=20):
    """
    ETA = prep time + travel time.
    Assumes average rider speed of 30 km/h in Accra traffic.
    """
    travel_minutes = int((distance_km / 30) * 60) if distance_km else 15
    return prep_time + travel_minutes


# ─────────────────────────────
# FOOD HOME — vendor map listing
# ─────────────────────────────
def food_home(request):
    """
    Uber Eats-style landing page.
    Shows vendor cards with distance, ETA, cuisine filter.
    """
    cuisine  = request.GET.get('cuisine', '')
    query    = request.GET.get('q', '').strip()
    user_lat = request.GET.get('lat')
    user_lng = request.GET.get('lng')

    vendors = FoodVendor.objects.filter(
        status__in=[FoodVendor.Status.OPEN, FoodVendor.Status.BUSY]
    ).prefetch_related('food_items')

    if cuisine:
        vendors = vendors.filter(cuisine=cuisine)
    if query:
        vendors = vendors.filter(
            Q(name__icontains=query) |
            Q(description__icontains=query) |
            Q(address__icontains=query)
        )

    # Annotate distance if user location provided
    vendor_list = []
    for v in vendors:
        distance = None
        eta      = None
        if user_lat and user_lng and v.latitude and v.longitude:
            try:
                distance = round(haversine_distance(
                    float(user_lat), float(user_lng),
                    v.latitude, v.longitude
                ), 1)
                eta = estimate_eta(distance, v.avg_prep_time)
            except Exception:
                pass
        vendor_list.append({
            'vendor':   v,
            'distance': distance,
            'eta':      eta,
        })

    # Sort by distance if available, else featured first
    vendor_list.sort(key=lambda x: (
        x['distance'] if x['distance'] is not None else 999
    ))

    cuisines = FoodVendor.CuisineType.choices

    # Get cart count for navbar
    food_cart_count = 0
    if request.user.is_authenticated:
        try:
            food_cart_count = request.user.food_cart.item_count
        except Exception:
            pass

    return render(request, 'food/home.html', {
        'vendor_list':      vendor_list,
        'cuisines':         cuisines,
        'selected_cuisine': cuisine,
        'query':            query,
        'food_cart_count':  food_cart_count,
        'cart_count':       0,
    })


# ─────────────────────────────
# VENDOR MENU PAGE
# ─────────────────────────────
def vendor_menu(request, slug):
    vendor     = get_object_or_404(FoodVendor, slug=slug)
    categories = vendor.food_categories.prefetch_related('items').all()
    all_items  = vendor.food_items.filter(is_available=True)

    food_cart_count = 0
    cart_vendor_id  = None
    if request.user.is_authenticated:
        try:
            cart = request.user.food_cart
            food_cart_count = cart.item_count
            cart_vendor_id  = cart.vendor_id
        except Exception:
            pass

    return render(request, 'food/menu.html', {
        'vendor':          vendor,
        'categories':      categories,
        'all_items':       all_items,
        'food_cart_count': food_cart_count,
        'cart_vendor_id':  cart_vendor_id,
        'cart_count':      0,
    })


# ─────────────────────────────
# CART API
# ─────────────────────────────
@login_required
@require_POST
def cart_add(request, item_id):
    food = get_object_or_404(FoodItem, pk=item_id, is_available=True)
    try:
        data = json.loads(request.body)
    except Exception:
        data = {}
    qty  = int(data.get('quantity', 1))
    note = data.get('note', '')

    cart, _ = FoodCart.objects.get_or_create(customer=request.user)

    # If cart has items from a different vendor, warn
    if cart.vendor and cart.vendor != food.vendor:
        return JsonResponse({
            'success':  False,
            'conflict': True,
            'message':  (
                f'Your cart has items from {cart.vendor.name}. '
                'Clear it to order from this restaurant.'
            ),
        })

    cart.vendor = food.vendor
    cart.save()

    item, created = FoodCartItem.objects.get_or_create(
        cart=cart, food=food,
        defaults={'quantity': qty, 'note': note},
    )
    if not created:
        item.quantity += qty
        item.note = note
        item.save()

    return JsonResponse({
        'success':    True,
        'cart_count': cart.item_count,
        'cart_total': str(cart.total),
    })


@login_required
@require_POST
def cart_update(request, item_id):
    try:
        data = json.loads(request.body)
    except Exception:
        data = {}
    qty = int(data.get('quantity', 1))

    cart_item = get_object_or_404(
        FoodCartItem, pk=item_id, cart__customer=request.user
    )
    if qty <= 0:
        cart_item.delete()
    else:
        cart_item.quantity = qty
        cart_item.save()

    cart = request.user.food_cart
    return JsonResponse({
        'success':    True,
        'cart_count': cart.item_count,
        'cart_total': str(cart.total),
    })


@login_required
@require_POST
def cart_clear(request):
    try:
        cart = request.user.food_cart
        cart.cart_items.all().delete()
        cart.vendor = None
        cart.save()
    except Exception:
        pass
    return JsonResponse({'success': True})


@login_required
def cart_data(request):
    try:
        cart  = request.user.food_cart
        items = cart.cart_items.select_related('food').all()
        return JsonResponse({
            'success': True,
            'vendor':  cart.vendor.name if cart.vendor else None,
            'vendor_slug': cart.vendor.slug if cart.vendor else None,
            'count':   cart.item_count,
            'total':   str(cart.total),
            'items': [
                {
                    'id':       i.pk,
                    'name':     i.food.name,
                    'price':    str(i.food.final_price),
                    'quantity': i.quantity,
                    'subtotal': str(i.subtotal),
                    'image':    i.food.image_url,
                    'note':     i.note,
                }
                for i in items
            ],
        })
    except Exception:
        return JsonResponse({
            'success': True, 'count': 0, 'total': '0',
            'items': [], 'vendor': None,
        })


# ─────────────────────────────
# PRICING API (called live as user types address)
# ─────────────────────────────
def price_estimate(request):
    """
    AJAX endpoint. Given pickup (vendor) and dropoff coords,
    returns distance, fee, and ETA.
    """
    try:
        vendor_lat  = float(request.GET.get('vlat'))
        vendor_lng  = float(request.GET.get('vlng'))
        dropoff_lat = float(request.GET.get('dlat'))
        dropoff_lng = float(request.GET.get('dlng'))
        prep_time   = int(request.GET.get('prep', 20))
    except (TypeError, ValueError):
        return JsonResponse({'success': False, 'error': 'Invalid coordinates'})

    distance = haversine_distance(vendor_lat, vendor_lng, dropoff_lat, dropoff_lng)
    fee      = calculate_delivery_fee(distance)
    eta      = estimate_eta(distance, prep_time)

    return JsonResponse({
        'success':     True,
        'distance_km': round(distance, 2),
        'fee':         str(fee),
        'eta_minutes': eta,
    })


# ─────────────────────────────
# CHECKOUT
# ─────────────────────────────
@login_required
def checkout(request):
    try:
        cart = request.user.food_cart
    except FoodCart.DoesNotExist:
        messages.error(request, 'Your cart is empty.')
        return redirect('food:home')

    if not cart.cart_items.exists():
        messages.error(request, 'Your cart is empty.')
        return redirect('food:home')

    vendor = cart.vendor

    if request.method == 'POST':
        address     = request.POST.get('delivery_address', '').strip()
        phone       = request.POST.get('delivery_phone', '').strip()
        note        = request.POST.get('delivery_note', '').strip()
        pay_method  = request.POST.get('payment_method', 'cash')
        dlat        = request.POST.get('delivery_lat')
        dlng        = request.POST.get('delivery_lng')
        fee_posted  = request.POST.get('delivery_fee', '0')
        dist_posted = request.POST.get('distance_km', '0')

        if not address:
            messages.error(request, 'Please enter your delivery address.')
            return redirect('food:checkout')
        if not phone:
            messages.error(request, 'Please enter your phone number.')
            return redirect('food:checkout')

        try:
            delivery_fee = Decimal(fee_posted)
            distance_km  = float(dist_posted) if dist_posted else None
        except Exception:
            delivery_fee = MIN_FARE
            distance_km  = None

        subtotal = cart.total

        # Create FoodOrder
        order = FoodOrder.objects.create(
            customer         = request.user,
            vendor           = vendor,
            delivery_address = address,
            delivery_lat     = float(dlat) if dlat else None,
            delivery_lng     = float(dlng) if dlng else None,
            delivery_phone   = phone,
            delivery_note    = note,
            subtotal         = subtotal,
            delivery_fee     = delivery_fee,
            distance_km      = distance_km,
            payment_method   = pay_method,
            payment_status   = (
                FoodOrder.PaymentStatus.UNPAID
            ),
            estimated_delivery_time = estimate_eta(
                distance_km or 5, vendor.avg_prep_time
            ),
        )

        # Create order items
        for ci in cart.cart_items.select_related('food').all():
            FoodOrderItem.objects.create(
                order    = order,
                food     = ci.food,
                name     = ci.food.name,
                price    = ci.food.final_price,
                quantity = ci.quantity,
                note     = ci.note,
            )

        # Create a Delivery record so riders can be assigned
        zone = DeliveryZone.objects.filter(is_active=True).first()
        delivery = Delivery.objects.create(
            booker           = request.user,
            pickup_location  = vendor.address,
            dropoff_location = address,
            pickup_lat       = vendor.latitude,
            pickup_lng       = vendor.longitude,
            dropoff_lat      = float(dlat) if dlat else None,
            dropoff_lng      = float(dlng) if dlng else None,
            delivery_fee     = delivery_fee,
            rider_commission = delivery_fee * Decimal('0.5'),
            distance_km      = distance_km,
            zone             = zone,
            delivery_type    = 'express',
            status           = 'pending',
            delivery_note    = note,
        )
        order.delivery = delivery
        order.save()

        # Auto-assign nearest available rider
        try:
            from delivery.views import _auto_assign_and_notify
            _auto_assign_and_notify(delivery)
        except Exception:
            pass

        # Update vendor order count
        vendor.total_orders += 1
        vendor.save(update_fields=['total_orders'])

        # Clear cart
        cart.cart_items.all().delete()
        cart.vendor = None
        cart.save()

        messages.success(
            request,
            f'Order {order.order_ref} placed! '
            f'Estimated delivery: {order.estimated_delivery_time} mins.'
        )
        return redirect('food:order_track', ref=order.order_ref)

    # GET — render checkout page
    # Try to pre-fill distance/fee if vendor has coords
    default_fee = str(MIN_FARE)

    return render(request, 'food/checkout.html', {
        'cart':        cart,
        'vendor':      vendor,
        'cart_items':  cart.cart_items.select_related('food').all(),
        'subtotal':    cart.total,
        'default_fee': default_fee,
        'user':        request.user,
        'cart_count':  0,
        'payment_methods': FoodOrder.PaymentMethod.choices,
        'vendor_lat':  vendor.latitude or '',
        'vendor_lng':  vendor.longitude or '',
    })


# ─────────────────────────────
# ORDER TRACKING
# ─────────────────────────────
@login_required
def order_track(request, ref):
    order = get_object_or_404(
        FoodOrder,
        order_ref=ref,
        customer=request.user,
    )
    return render(request, 'food/track.html', {
        'order':      order,
        'cart_count': 0,
    })


@login_required
def order_track_api(request, ref):
    """AJAX polling endpoint for live order status."""
    order = get_object_or_404(FoodOrder, order_ref=ref, customer=request.user)

    rider_lat = rider_lng = None
    rider_name = rider_phone = None

    if order.delivery and order.delivery.rider:
        try:
            from rider.models import RiderLocation
            loc = RiderLocation.objects.get(
                rider=order.delivery.rider.rider, is_active=True
            )
            rider_lat  = float(loc.latitude)
            rider_lng  = float(loc.longitude)
        except Exception:
            pass
        rp = order.delivery.rider
        rider_name  = rp.rider.get_full_name() or rp.rider.phone
        rider_phone = rp.rider.phone

    return JsonResponse({
        'status':       order.status,
        'status_label': order.get_status_display(),
        'rider_lat':    rider_lat,
        'rider_lng':    rider_lng,
        'rider_name':   rider_name,
        'rider_phone':  rider_phone,
        'eta':          order.estimated_delivery_time,
    })


# ─────────────────────────────
# ORDER HISTORY
# ─────────────────────────────
@login_required
def order_history(request):
    orders = FoodOrder.objects.filter(
        customer=request.user
    ).order_by('-created_at')
    return render(request, 'food/orders.html', {
        'orders':     orders,
        'cart_count': 0,
    })
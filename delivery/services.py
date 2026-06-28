import math
from decimal import Decimal
from django.db import transaction
from django.utils import timezone


# ── DISTANCE ──────────────────────────────────────────────

def calculate_distance(lat1, lng1, lat2, lng2):
    """Haversine formula — returns straight-line distance in km."""
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) *
         math.cos(math.radians(lat2)) *
         math.sin(dlng / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


# ── FEE CALCULATION ───────────────────────────────────────

# Pricing constants — tweak these to match your market
BASE_FEE       = Decimal('5.00')   # GHS charged for any distance
PER_KM_RATE    = Decimal('2.00')   # GHS per km
MIN_FEE        = Decimal('5.00')   # never below this
MAX_FEE        = Decimal('80.00')  # cap so upcountry doesn't blow up
ACCRA_CENTER   = (5.6037, -0.1870) # fallback pickup if vendor has no coords


def calculate_delivery_fee(distance_km):
    """
    Uber-style distance fee.
    Returns a Decimal rounded to 2 places.
    """
    if distance_km is None or distance_km <= 0:
        return MIN_FEE
    fee = BASE_FEE + (Decimal(str(round(distance_km, 2))) * PER_KM_RATE)
    return max(MIN_FEE, min(MAX_FEE, fee.quantize(Decimal('0.01'))))


def estimate_fee_for_request(pickup_lat, pickup_lng, dropoff_lat, dropoff_lng):
    """
    Public helper — called by the checkout fee-preview AJAX endpoint.
    Returns (distance_km, fee_decimal).
    """
    distance = calculate_distance(pickup_lat, pickup_lng, dropoff_lat, dropoff_lng)
    fee      = calculate_delivery_fee(distance)
    return round(distance, 2), fee


# ── RIDER FINDER ──────────────────────────────────────────

def find_best_rider(pickup_lat, pickup_lng):
    """
    Find the best available, verified rider by:
      1. Straight-line distance to pickup point
      2. Workload penalty (2 km equivalent per active job)
    Zone field on RiderProfile is kept for admin grouping but no longer
    used as a hard filter — nearest rider wins regardless of zone.
    Returns RiderProfile or None.
    """
    from rider.models import RiderProfile
    from delivery.models import Delivery

    riders = RiderProfile.objects.filter(
        status=RiderProfile.Status.AVAILABLE,
        is_verified=True,
    ).select_related('rider')

    if not riders.exists():
        return None

    best_rider = None
    best_score = float('inf')

    for rider in riders:
        if rider.current_lat is not None and rider.current_lng is not None:
            distance = calculate_distance(
                pickup_lat, pickup_lng,
                rider.current_lat, rider.current_lng,
            )
        else:
            distance = 999  # no GPS — deprioritize but don't exclude

        active_jobs = Delivery.objects.filter(
            rider=rider,
            status__in=[
                Delivery.Status.ASSIGNED,
                Delivery.Status.PICKED_UP,
                Delivery.Status.EN_ROUTE,
            ]
        ).count()

        score = distance + (active_jobs * 2)

        if score < best_score:
            best_score = score
            best_rider = rider

    return best_rider


# ── RIDER ASSIGNMENT ──────────────────────────────────────

def assign_rider_to_delivery(delivery, notify=True):
    """
    Assign the nearest available rider to a Delivery.
    Works for both product orders and food orders.
    Returns RiderProfile or None.
    """
    from rider.models import RiderProfile, DeliveryAcceptance

    pickup_lat = delivery.pickup_lat or ACCRA_CENTER[0]
    pickup_lng = delivery.pickup_lng or ACCRA_CENTER[1]

    rider = find_best_rider(pickup_lat, pickup_lng)

    if not rider:
        return None

    with transaction.atomic():
        rate = Decimal(str(rider.commission_rate)) / Decimal('100')
        delivery.rider_commission = (
            Decimal(str(delivery.delivery_fee)) * rate
        ).quantize(Decimal('0.01'))
        delivery.rider       = rider
        delivery.status      = delivery.Status.ASSIGNED
        delivery.assigned_at = timezone.now()
        delivery.save(update_fields=[
            'rider', 'status', 'assigned_at', 'rider_commission'
        ])

        rider.status = RiderProfile.Status.ON_DELIVERY
        rider.save(update_fields=['status'])

        DeliveryAcceptance.objects.get_or_create(
            delivery=delivery,
            defaults={'rider': rider, 'status': DeliveryAcceptance.Status.PENDING},
        )

    if notify:
        _notify_rider(rider, delivery)

    return rider


# ── PRODUCT ORDER ASSIGNMENT ──────────────────────────────

def auto_assign_for_order(order):
    """
    Called after a product Order is paid and delivery_choice == 'rider'.
    Calculates distance-based fee, creates Delivery, assigns nearest rider.
    """
    from delivery.models import Delivery

    # Avoid duplicate delivery
    try:
        if order.delivery:
            return order.delivery
    except Exception:
        pass

    # Pickup coords — from vendor, fallback to Accra center
    pickup_lat = pickup_lng = None
    first_item = order.items.select_related('product__vendor').first()
    if first_item and first_item.product and first_item.product.vendor:
        vendor     = first_item.product.vendor
        pickup_lat = getattr(vendor, 'latitude',  None)
        pickup_lng = getattr(vendor, 'longitude', None)

    pickup_lat = pickup_lat or ACCRA_CENTER[0]
    pickup_lng = pickup_lng or ACCRA_CENTER[1]

    # Dropoff coords — from order (set at checkout via geolocation)
    dropoff_lat = getattr(order, 'dropoff_lat', None)
    dropoff_lng = getattr(order, 'dropoff_lng', None)

    # Calculate distance + fee
    if dropoff_lat and dropoff_lng:
        distance_km  = calculate_distance(pickup_lat, pickup_lng, dropoff_lat, dropoff_lng)
        delivery_fee = calculate_delivery_fee(distance_km)
    else:
        # No coords — use minimum fee
        distance_km  = None
        delivery_fee = MIN_FEE

    # Update order with final fee
    order.delivery_fee  = delivery_fee
    order.total_amount  = order.subtotal + delivery_fee
    order.distance_km   = distance_km
    order.save(update_fields=['delivery_fee', 'total_amount', 'distance_km'])

    delivery = Delivery.objects.create(
        order            = order,
        booker           = order.customer,
        pickup_location  = getattr(first_item.product.vendor, 'location', 'Vendor') if first_item else 'Vendor',
        dropoff_location = f'{order.delivery_address}, {order.delivery_city}',
        pickup_lat       = pickup_lat,
        pickup_lng       = pickup_lng,
        dropoff_lat      = dropoff_lat,
        dropoff_lng      = dropoff_lng,
        delivery_fee     = delivery_fee,
        distance_km      = distance_km,
        rider_commission = 0,
        zone             = None,           # no zone — distance-based
        delivery_type    = Delivery.DeliveryType.EXPRESS,
        status           = Delivery.Status.PENDING,
    )

    assign_rider_to_delivery(delivery)
    return delivery


# ── FOOD ORDER ASSIGNMENT ─────────────────────────────────

def auto_assign_for_food_order(food_order):
    """
    Called after a FoodOrder is paid.
    Uses existing delivery if already created, otherwise creates one.
    """
    from delivery.models import Delivery

    delivery = getattr(food_order, 'delivery', None)

    if not delivery:
        pickup_lat = getattr(food_order.vendor, 'latitude',  None) or ACCRA_CENTER[0]
        pickup_lng = getattr(food_order.vendor, 'longitude', None) or ACCRA_CENTER[1]
        dropoff_lat = getattr(food_order, 'delivery_lat', None)
        dropoff_lng = getattr(food_order, 'delivery_lng', None)

        if dropoff_lat and dropoff_lng:
            distance_km  = calculate_distance(pickup_lat, pickup_lng, dropoff_lat, dropoff_lng)
            delivery_fee = calculate_delivery_fee(distance_km)
        else:
            distance_km  = None
            delivery_fee = food_order.delivery_fee or MIN_FEE

        delivery = Delivery.objects.create(
            booker           = food_order.customer,
            pickup_location  = getattr(food_order.vendor, 'address', ''),
            dropoff_location = food_order.delivery_address,
            pickup_lat       = pickup_lat,
            pickup_lng       = pickup_lng,
            dropoff_lat      = dropoff_lat,
            dropoff_lng      = dropoff_lng,
            delivery_fee     = delivery_fee,
            distance_km      = distance_km,
            rider_commission = 0,
            zone             = None,
            delivery_type    = Delivery.DeliveryType.EXPRESS,
            status           = Delivery.Status.PENDING,
            delivery_note    = getattr(food_order, 'delivery_note', ''),
        )
        food_order.delivery = delivery
        food_order.save(update_fields=['delivery'])

    if delivery.status == Delivery.Status.PENDING:
        assign_rider_to_delivery(delivery)

    return delivery


# ── RIDER NOTIFICATION ────────────────────────────────────

def _notify_rider(rider, delivery):
    """Send in-app notification to rider — never crashes order flow."""
    try:
        from rider.views import notify_rider

        order_ref  = ''
        order_type = '📦 Product'

        if delivery.order:
            order_ref = delivery.order.order_ref
        elif hasattr(delivery, 'food_order') and delivery.food_order:
            order_ref  = delivery.food_order.order_ref
            order_type = '🍔 Food'

        distance_line = (
            f' Distance: {round(delivery.distance_km, 1)} km.'
            if delivery.distance_km else ''
        )

        notify_rider(
            rider_user = rider.rider,
            title      = f'🛵 New Delivery — {order_ref}',
            message    = (
                f'{order_type} order {order_ref} assigned to you.'
                f'{distance_line}'
                f' Pickup: {delivery.pickup_location or "See dashboard"}.'
                f' Commission: GHS {delivery.rider_commission}.'
                f' Please accept in your dashboard.'
            ),
            notif_type = 'new_delivery',
            link       = '/rider/',
        )
    except Exception:
        pass
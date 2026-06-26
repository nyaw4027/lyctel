import math
from django.db import transaction
from django.utils import timezone


def calculate_distance(lat1, lng1, lat2, lng2):
    """Haversine formula — returns distance in km."""
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) *
         math.cos(math.radians(lat2)) *
         math.sin(dlng / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def find_best_rider(pickup_lat, pickup_lng, zone=None):
    """
    Find the best available rider using:
    - Zone priority
    - Nearest GPS location
    - Workload balancing (active jobs penalty)
    Returns RiderProfile or None.
    """
    from rider.models import RiderProfile
    from delivery.models import Delivery

    riders = RiderProfile.objects.filter(
        status=RiderProfile.Status.AVAILABLE,
        is_verified=True,
    ).select_related('zone')

    if not riders.exists():
        return None

    # Prioritize riders in the same delivery zone
    if zone:
        zone_riders = riders.filter(zone=zone)
        if zone_riders.exists():
            riders = zone_riders

    best_rider = None
    best_score = float('inf')

    for rider in riders:
        if rider.current_lat is None or rider.current_lng is None:
            distance = 999  # no GPS — deprioritize but don't exclude
        else:
            distance = calculate_distance(
                pickup_lat, pickup_lng,
                rider.current_lat, rider.current_lng,
            )

        # Each active job adds 2km equivalent penalty
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


def assign_rider_to_delivery(delivery, notify=True):
    """
    Assign the best available rider to a Delivery object.
    Works for both product orders and food orders.
    Returns RiderProfile or None.
    """
    from rider.models import RiderProfile, DeliveryAcceptance

    pickup_lat = delivery.pickup_lat or 5.6037
    pickup_lng = delivery.pickup_lng or -0.1870

    rider = find_best_rider(pickup_lat, pickup_lng, zone=delivery.zone)

    if not rider:
        return None

    with transaction.atomic():
        # Calculate rider commission
        from decimal import Decimal
        rate = Decimal(str(rider.commission_rate)) / Decimal('100')
        delivery.rider_commission = (Decimal(str(delivery.delivery_fee)) * rate).quantize(Decimal('0.01'))
        delivery.rider       = rider
        delivery.status      = delivery.Status.ASSIGNED
        delivery.assigned_at = timezone.now()
        delivery.save(update_fields=['rider', 'status', 'assigned_at', 'rider_commission'])

        rider.status = RiderProfile.Status.ON_DELIVERY
        rider.save(update_fields=['status'])

        # Create acceptance record so rider sees it in dashboard
        DeliveryAcceptance.objects.get_or_create(
            delivery=delivery,
            defaults={'rider': rider, 'status': DeliveryAcceptance.Status.PENDING},
        )

    if notify:
        _notify_rider(rider, delivery)

    return rider

    try:
        from push_notifications import push_rider_assigned
        push_rider_assigned(delivery)
    except Exception:
        pass


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

        notify_rider(
            rider_user=rider.rider,
            title=f'🛵 New Delivery — {order_ref}',
            message=(
                f'{order_type} order {order_ref} assigned to you. '
                f'Pickup: {delivery.pickup_location or "See dashboard"}. '
                f'Commission: GHS {delivery.rider_commission}. '
                f'Please accept in your dashboard.'
            ),
            notif_type='new_delivery',
            link='/rider/',
        )
    except Exception:
        pass


def auto_assign_for_order(order):
    """
    Called after a product Order is paid.
    Creates a Delivery and assigns the nearest available rider.
    """
    from delivery.models import Delivery, DeliveryZone

    # Avoid duplicate delivery
    try:
        if order.delivery:
            return order.delivery
    except Exception:
        pass

    zone = DeliveryZone.objects.filter(is_active=True).first()

    # Try to get pickup coords from first product's vendor
    pickup_lat = pickup_lng = None
    first_item = order.items.select_related('product__vendor').first()
    if first_item and first_item.product and first_item.product.vendor:
        vendor = first_item.product.vendor
        pickup_lat = getattr(vendor, 'latitude', None)
        pickup_lng = getattr(vendor, 'longitude', None)

    delivery = Delivery.objects.create(
        order            = order,
        booker           = order.customer,
        pickup_location  = 'Vendor / Warehouse',
        dropoff_location = f'{order.delivery_address}, {order.delivery_city}',
        pickup_lat       = pickup_lat,
        pickup_lng       = pickup_lng,
        delivery_fee     = order.delivery_fee,
        rider_commission = 0,
        zone             = zone,
        delivery_type    = Delivery.DeliveryType.STANDARD,
        status           = Delivery.Status.PENDING,
    )

    assign_rider_to_delivery(delivery)
    return delivery


def auto_assign_for_food_order(food_order):
    """
    Called after a FoodOrder is paid.
    Uses existing delivery if created at checkout, otherwise creates one.
    """
    from delivery.models import Delivery, DeliveryZone

    delivery = getattr(food_order, 'delivery', None)

    if not delivery:
        zone = DeliveryZone.objects.filter(is_active=True).first()
        delivery = Delivery.objects.create(
            booker           = food_order.customer,
            pickup_location  = food_order.vendor.address,
            dropoff_location = food_order.delivery_address,
            pickup_lat       = food_order.vendor.latitude,
            pickup_lng       = food_order.vendor.longitude,
            dropoff_lat      = food_order.delivery_lat,
            dropoff_lng      = food_order.delivery_lng,
            delivery_fee     = food_order.delivery_fee,
            rider_commission = 0,
            zone             = zone,
            delivery_type    = Delivery.DeliveryType.EXPRESS,
            status           = Delivery.Status.PENDING,
            delivery_note    = food_order.delivery_note,
        )
        food_order.delivery = delivery
        food_order.save(update_fields=['delivery'])

    if delivery.status == Delivery.Status.PENDING:
        assign_rider_to_delivery(delivery)

    return delivery
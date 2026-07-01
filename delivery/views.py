import json

from django.shortcuts import render, get_object_or_404, redirect
from django.utils.timezone import now
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from order.models import Order
from .models import Delivery, DeliveryTracking, DeliveryZone
from rider.models import RiderProfile, DeliveryAcceptance
from .utils import haversine_distance, calculate_distance, calculate_delivery_fee, estimate_eta_minutes
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer



# ─────────────────────────────
# CREATE DELIVERY AFTER ORDER
# ─────────────────────────────
def create_delivery(order):
    zone = DeliveryZone.objects.filter(is_active=True).first()

    delivery, created = Delivery.objects.get_or_create(
        order=order,
        defaults={
            "zone": zone,
            "delivery_fee": zone.delivery_fee if zone else 0,
        }
    )
    return delivery


# ─────────────────────────────
# CUSTOMER TRACKING PAGE
# ─────────────────────────────
@login_required
def track_delivery(request, order_ref):
    delivery = get_object_or_404(
        Delivery.objects.select_related("order", "rider"),
        order__order_ref=order_ref
    )

    # AJAX live polling (optional)
    if request.GET.get("live") == "1":
        return JsonResponse({
            "lat": delivery.current_lat,
            "lng": delivery.current_lng,
            "status": delivery.status
        })

    return render(request, "delivery/track.html", {
        "delivery": delivery
    })


# ─────────────────────────────
# RIDER DASHBOARD
# ─────────────────────────────
@login_required
def rider_dashboard(request):
    deliveries = Delivery.objects.filter(rider__rider=request.user)

    return render(request, "delivery/rider_dashboard.html", {
        "deliveries": deliveries
    })


# ─────────────────────────────
# UPDATE DELIVERY STATUS
# ─────────────────────────────
@login_required
def update_delivery_status(request, delivery_id, status):
    if request.method != "POST":
        return redirect("delivery:rider_dashboard")

    delivery = get_object_or_404(Delivery, id=delivery_id)

    # Security check
    if delivery.rider and delivery.rider.rider != request.user:
        return redirect("delivery:rider_dashboard")

    delivery.status = status

    if status == "picked_up":
        delivery.picked_up_at = now()

    elif status == "delivered":
        delivery.delivered_at = now()

    delivery.save()

    return redirect("delivery:rider_dashboard")


# ─────────────────────────────
# RIDER LIVE LOCATION UPDATE
# ─────────────────────────────
@csrf_exempt
def update_rider_location(request, delivery_id):
    if request.method != "POST":
        return JsonResponse({"error": "POST required"}, status=400)

    try:
        data = json.loads(request.body)

        lat = float(data.get("lat"))
        lng = float(data.get("lng"))

        delivery = get_object_or_404(Delivery, pk=delivery_id)

        # Update live position
        delivery.current_lat = lat
        delivery.current_lng = lng
        delivery.save()

        # Save tracking history
        DeliveryTracking.objects.create(
            delivery=delivery,
            latitude=lat,
            longitude=lng
        )

        # Send real-time update via WebSocket (includes current status for the tracker)
        channel_layer = get_channel_layer()
        async_to_sync(channel_layer.group_send)(
            f"delivery_{delivery_id}",
            {
                "type": "send_location",
                "lat": lat,
                "lng": lng,
                "status": delivery.status,
            }
        )

        return JsonResponse({
            "success": True,
            "status": delivery.status
        })

    except Exception as e:
        return JsonResponse({"error": str(e)}, status=400)


# ─────────────────────────────
# TRACKING DATA API (MAP / AJAX)
# ─────────────────────────────
@login_required
def tracking_data(request, delivery_id):
    delivery = get_object_or_404(Delivery, pk=delivery_id)

    return JsonResponse({
        "lat": delivery.current_lat,
        "lng": delivery.current_lng,
        "status": delivery.status
    })


# ─────────────────────────────
# AUTO ASSIGN NEAREST RIDER
# ─────────────────────────────
@login_required
def assign_nearest_rider(request, delivery_id):
    delivery = get_object_or_404(Delivery, id=delivery_id)

    if not delivery.pickup_lat or not delivery.pickup_lng:
        return JsonResponse({"error": "Pickup location missing"})

    riders = RiderProfile.objects.filter(status="available")

    nearest_rider = None
    min_distance = float("inf")

    for rider in riders:
        if rider.rider and rider.current_lat and rider.current_lng:
            distance = calculate_distance(
                delivery.pickup_lat,
                delivery.pickup_lng,
                rider.current_lat,
                rider.current_lng
            )

            if distance < min_distance:
                min_distance = distance
                nearest_rider = rider

    if not nearest_rider:
        return JsonResponse({"error": "No available rider"})

    # Assign rider
    delivery.rider = nearest_rider
    delivery.status = "assigned"
    delivery.save()

    nearest_rider.status = "on_delivery"
    nearest_rider.save()

    return JsonResponse({
        "success": True,
        "rider": nearest_rider.rider.username,
        "distance_km": round(min_distance, 2)
    })


# ─────────────────────────────
# CREATE ORDER + DELIVERY
# ─────────────────────────────
@login_required
def create_order(request):
    order = Order.objects.create(
        user=request.user,
        total_price=0  # Replace with real calculation
    )

    create_delivery(order)

    return redirect("order:success")


# ─────────────────────────────
# BOOK A RIDE (CUSTOMER / VENDOR)
# ─────────────────────────────
@login_required
def book_ride(request):
    """Any authenticated user (customer or vendor) books a standalone ride."""
    zones = DeliveryZone.objects.filter(is_active=True)

    if request.method == "POST":
        pickup  = request.POST.get("pickup_location", "").strip()
        dropoff = request.POST.get("dropoff_location", "").strip()
        pickup_lat  = request.POST.get("pickup_lat") or None
        pickup_lng  = request.POST.get("pickup_lng") or None
        dropoff_lat = request.POST.get("dropoff_lat") or None
        dropoff_lng = request.POST.get("dropoff_lng") or None
        zone_id = request.POST.get("zone_id")
        note    = request.POST.get("note", "")

        if not pickup or not dropoff:
            messages.error(request, "Pickup and dropoff locations are required.")
            return render(request, "delivery/book_ride.html", {"zones": zones})

        zone = DeliveryZone.objects.filter(pk=zone_id, is_active=True).first()

        delivery = Delivery.objects.create(
            booker=request.user,
            pickup_location=pickup,
            dropoff_location=dropoff,
            pickup_lat=float(pickup_lat) if pickup_lat else None,
            pickup_lng=float(pickup_lng) if pickup_lng else None,
            dropoff_lat=float(dropoff_lat) if dropoff_lat else None,
            dropoff_lng=float(dropoff_lng) if dropoff_lng else None,
            zone=zone,
            delivery_type=Delivery.DeliveryType.EXPRESS,
            delivery_note=note,
            status=Delivery.Status.PENDING,
        )

        _auto_assign_and_notify(delivery)

        messages.success(request, "Ride booked! We're finding you a rider...")
        return redirect("delivery:track_ride", pk=delivery.pk)

    return render(request, "delivery/book_ride.html", {"zones": zones})


# ─────────────────────────────
# LIVE TRACKING (STANDALONE RIDE)
# ─────────────────────────────
@login_required
def track_ride(request, pk):
    """Live WebSocket tracking page for a standalone ride booking."""
    delivery = get_object_or_404(Delivery, pk=pk)

    is_rider  = delivery.rider and delivery.rider.rider == request.user
    is_booker = delivery.booker == request.user

    if not is_booker and not is_rider and not request.user.role in ("admin", "staff"):
        messages.error(request, "Access denied.")
        return redirect("frontend:home")

    return render(request, "delivery/track_live.html", {"delivery": delivery})


# ─────────────────────────────
# VENDOR ASSIGNS RIDER MANUALLY
# ─────────────────────────────
@login_required
def vendor_assign_rider(request, delivery_id, rider_id):
    """POST-only: vendor manually assigns a specific rider to a pending delivery."""
    if request.method != "POST":
        return JsonResponse({"error": "POST required"}, status=405)

    delivery = get_object_or_404(Delivery, pk=delivery_id, status=Delivery.Status.PENDING)
    rider    = get_object_or_404(RiderProfile, pk=rider_id, status=RiderProfile.Status.AVAILABLE)

    acceptance, created = DeliveryAcceptance.objects.get_or_create(
        delivery=delivery,
        defaults={"rider": rider, "status": DeliveryAcceptance.Status.PENDING},
    )
    if not created:
        acceptance.rider  = rider
        acceptance.status = DeliveryAcceptance.Status.PENDING
        acceptance.responded_at = None
        acceptance.save()

    _push_prompt_to_rider(rider, delivery, acceptance)

    # Persist a notification in the DB so the rider sees it even if offline
    from rider.views import notify_rider
    notify_rider(
        rider.rider,
        "New Delivery Request",
        f"Pickup: {delivery.pickup_location or getattr(getattr(delivery, 'order', None), 'delivery_address', 'N/A')}",
        notif_type="new_delivery",
        link="/rider/",
    )

    return JsonResponse({
        "success": True,
        "rider": rider.rider.get_full_name() or rider.rider.phone,
    })


# ─────────────────────────────
# INTERNAL HELPERS
# ─────────────────────────────
def _auto_assign_and_notify(delivery):
    """Pick nearest available rider, create DeliveryAcceptance, push WS prompt."""
    riders = RiderProfile.objects.filter(
        status=RiderProfile.Status.AVAILABLE
    ).select_related("rider")

    chosen = None

    if delivery.pickup_lat and delivery.pickup_lng:
        min_dist = float("inf")
        for rp in riders:
            if rp.current_lat and rp.current_lng:
                d = calculate_distance(
                    delivery.pickup_lat, delivery.pickup_lng,
                    rp.current_lat, rp.current_lng,
                )
                if d < min_dist:
                    min_dist = d
                    chosen = rp

    if not chosen:
        chosen = riders.first()

    if chosen:
        acceptance, _ = DeliveryAcceptance.objects.get_or_create(
            delivery=delivery,
            defaults={"rider": chosen, "status": DeliveryAcceptance.Status.PENDING},
        )
        _push_prompt_to_rider(chosen, delivery, acceptance)

        from rider.views import notify_rider
        notify_rider(
            chosen.rider,
            "New Ride Request",
            f"Pickup: {delivery.pickup_location}  →  {delivery.dropoff_location}",
            notif_type="new_delivery",
            link="/rider/",
        )


def _push_prompt_to_rider(rider_profile, delivery, acceptance):
    """Send a real-time ride_request event to the rider's WebSocket group."""
    channel_layer = get_channel_layer()
    commission = str(delivery.calculate_commission())
    async_to_sync(channel_layer.group_send)(
        f"rider_{rider_profile.rider.id}",
        {
            "type": "ride_request",
            "delivery_id": delivery.pk,
            "acceptance_id": acceptance.pk,
            "pickup": delivery.pickup_location or "",
            "dropoff": delivery.dropoff_location or "",
            "fee": str(delivery.delivery_fee),
            "commission": commission,
        }
    )


    
def price_estimate(request):
    """
    GET /delivery/api/price-estimate/
    ?olat=5.6&olng=-0.18&dlat=5.65&dlng=-0.19
    Returns: { success, distance_km, fee, eta_minutes }
    """
    try:
        origin_lat  = float(request.GET.get('olat'))
        origin_lng  = float(request.GET.get('olng'))
        dropoff_lat = float(request.GET.get('dlat'))
        dropoff_lng = float(request.GET.get('dlng'))
    except (TypeError, ValueError):
        return JsonResponse({'success': False, 'error': 'Invalid coordinates'})
 
    distance = haversine_distance(origin_lat, origin_lng, dropoff_lat, dropoff_lng)
    fee      = calculate_delivery_fee(distance)
    eta      = estimate_eta_minutes(distance)
 
    return JsonResponse({
        'success':     True,
        'distance_km': round(distance, 2),
        'fee':         str(fee),
        'eta_minutes': eta,
    })
 
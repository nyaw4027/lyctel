import json

from django.shortcuts import render, get_object_or_404, redirect
from django.utils.timezone import now
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from order.models import Order
from .models import Delivery, DeliveryTracking, DeliveryZone
from rider.models import RiderProfile
from .utils import calculate_distance

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

        # Send real-time update via WebSocket
        channel_layer = get_channel_layer()
        async_to_sync(channel_layer.group_send)(
            f"delivery_{delivery_id}",
            {
                "type": "send_location",
                "lat": lat,
                "lng": lng,
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
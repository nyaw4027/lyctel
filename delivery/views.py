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

    # security check
    if delivery.rider and delivery.rider.user != request.user:
        return redirect("delivery:rider_dashboard")

    delivery.status = status

    if status == "picked_up":
        delivery.picked_up_at = timezone.now()

    elif status == "delivered":
        delivery.delivered_at = timezone.now()

    delivery.save()

    return redirect("delivery:rider_dashboard")


# ─────────────────────────────
# RIDER LIVE LOCATION UPDATE (AJAX)
# ─────────────────────────────
@csrf_exempt
def update_rider_location(request, delivery_id):
    if request.method == "POST":
        delivery = get_object_or_404(Delivery, id=delivery_id)

        lat = request.POST.get("latitude")
        lng = request.POST.get("longitude")

        if lat and lng:
            # 1. Save to DB
            delivery.current_lat = float(lat)
            delivery.current_lng = float(lng)
            delivery.save()

            # 2. SEND LIVE UPDATE TO WEB SOCKET
            channel_layer = get_channel_layer()

            async_to_sync(channel_layer.group_send)(
                f"delivery_{delivery_id}",
                {
                    "type": "send_location",
                    "lat": float(lat),
                    "lng": float(lng),
                }
            )

            return JsonResponse({"status": "success"})

        return JsonResponse({"status": "missing data"})

    return JsonResponse({"status": "invalid request"})

# ─────────────────────────────
# TRACKING API FOR GOOGLE MAPS
# ─────────────────────────────
@login_required
def tracking_data(request, delivery_id):
    delivery = get_object_or_404(Delivery, id=delivery_id)

    latest = delivery.tracking.order_by("-timestamp").first()

    if not latest:
        return JsonResponse({"error": "No tracking data"})

    return JsonResponse({
        "lat": latest.latitude,
        "lng": latest.longitude,
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
        if rider.rider:  # ensure linked user exists
            # You may extend RiderProfile with lat/lng if needed
            if hasattr(rider, "current_lat") and hasattr(rider, "current_lng"):
                if rider.current_lat and rider.current_lng:
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

    # assign rider
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
# CREATE ORDER + AUTO DELIVERY
# ─────────────────────────────
def create_order(request):
    order = Order.objects.create(
        user=request.user,
        total_price=0  # replace with your logic
    )

    create_delivery(order)

    return redirect("orders:success")




@csrf_exempt
def update_rider_location(request, pk):
    """
    Rider sends live GPS location here
    """

    if request.method != "POST":
        return JsonResponse({"error": "POST required"}, status=400)

    try:
        data = json.loads(request.body)

        lat = float(data.get("lat"))
        lng = float(data.get("lng"))

        delivery = Delivery.objects.get(pk=pk)

        # update current rider location
        delivery.current_lat = lat
        delivery.current_lng = lng
        delivery.save()

        # save tracking history
        DeliveryTracking.objects.create(
            delivery=delivery,
            latitude=lat,
            longitude=lng
        )

        return JsonResponse({
            "success": True,
            "status": delivery.status
        })

    except Exception as e:
        return JsonResponse({"error": str(e)}, status=400)



def tracking_data(request, pk):
    delivery = Delivery.objects.get(pk=pk)

    return JsonResponse({
        "lat": delivery.current_lat,
        "lng": delivery.current_lng,
        "status": delivery.status
    })

 
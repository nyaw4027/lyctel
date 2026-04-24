from django.db import transaction
from rider.models import RiderProfile
from .models import Delivery
from .utils import calculate_distance


def assign_nearest_rider(delivery):
    """
    Smart rider assignment engine:
    - nearest location
    - zone priority
    - workload balancing
    - safe atomic assignment
    """

    if not delivery.pickup_lat or not delivery.pickup_lng:
        return None

    # ─────────────────────────────
    # GET AVAILABLE RIDERS
    # ─────────────────────────────
    riders = RiderProfile.objects.filter(
        status=RiderProfile.Status.AVAILABLE,
        is_verified=True
    )

    if delivery.zone:
        zone_riders = riders.filter(zone=delivery.zone)
        if zone_riders.exists():
            riders = zone_riders  # prioritize zone match

    best_rider = None
    best_score = float("inf")

    for rider in riders:

        if rider.current_lat is None or rider.current_lng is None:
            continue

        # ─────────────────────────────
        # DISTANCE CALCULATION
        # ─────────────────────────────
        distance = calculate_distance(
            delivery.pickup_lat,
            delivery.pickup_lng,
            rider.current_lat,
            rider.current_lng
        )

        # ─────────────────────────────
        # LOAD BALANCING (IMPORTANT UPGRADE)
        # ─────────────────────────────
        active_jobs = Delivery.objects.filter(
            rider=rider,
            status__in=[
                Delivery.Status.ASSIGNED,
                Delivery.Status.PICKED_UP,
                Delivery.Status.EN_ROUTE
            ]
        ).count()

        # Weighted score:
        # distance + workload penalty
        score = distance + (active_jobs * 2)

        if score < best_score:
            best_score = score
            best_rider = rider

    if not best_rider:
        return None

    # ─────────────────────────────
    # SAFE ASSIGNMENT (ATOMIC)
    # ─────────────────────────────
    with transaction.atomic():

        delivery.rider = best_rider
        delivery.status = Delivery.Status.ASSIGNED
        delivery.assigned_at = delivery.assigned_at or delivery.created_at
        delivery.save()

        best_rider.status = RiderProfile.Status.ON_DELIVERY
        best_rider.save()

    return best_rider
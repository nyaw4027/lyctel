"""
delivery/utils.py — Uber-style delivery fee calculation for product orders.
Mirrors the same engine used in food/views.py for consistency.
"""
import math
from decimal import Decimal

# ── PRICING CONFIG ─────────────────────────────────────────
BASE_FARE    = Decimal('5.00')   # flat base fee every delivery starts at
PER_KM_RATE  = Decimal('2.50')  # per kilometre charge
MIN_FARE     = Decimal('8.00')  # floor — no delivery cheaper than this
SURGE_FACTOR = Decimal('1.0')   # multiply for surge pricing (future use)


def haversine_distance(lat1, lng1, lat2, lng2):
    """Straight-line distance between two GPS coordinates in kilometres."""
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) *
         math.cos(math.radians(lat2)) *
         math.sin(dlng / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def calculate_delivery_fee(distance_km):
    """Returns a Decimal delivery fee for the given distance."""
    if not distance_km or distance_km <= 0:
        return MIN_FARE
    fee = BASE_FARE + (Decimal(str(round(distance_km, 4))) * PER_KM_RATE * SURGE_FACTOR)
    return max(fee, MIN_FARE).quantize(Decimal('0.01'))


def estimate_eta_minutes(distance_km, prep_time=10):
    """Estimated delivery time in minutes (prep + road travel at 30 km/h average)."""
    travel = int((distance_km / 30) * 60) if distance_km else 15
    return prep_time + travel


def calculate_rider_commission(delivery_fee, rate_percent=Decimal('50')):
    """Rider gets 50%, app keeps 45%, 5% is the app's rider cut."""
    return (delivery_fee * rate_percent / Decimal('100')).quantize(Decimal('0.01'))


def calculate_app_cut(delivery_fee, rate_percent=Decimal('5')):
    """5% of delivery fee goes to Lynctel from every delivery."""
    return (delivery_fee * rate_percent / Decimal('100')).quantize(Decimal('0.01'))

def calculate_distance(lat1, lng1, lat2, lng2):
    """
    Compatibility wrapper for distance calculation.
    Returns the distance in kilometres.
    """
    return haversine_distance(lat1, lng1, lat2, lng2)
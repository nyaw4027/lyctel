import requests
from django.conf import settings
from django.core.cache import cache

GOOGLE_MAPS_API_KEY = settings.GOOGLE_MAPS_API_KEY


def get_google_eta(origin_lat, origin_lng, dest_lat, dest_lng):
    """
    Returns real road ETA in minutes using Google Directions API
    Includes caching + safe fallback handling
    """

    # ─────────────────────────────
    # CACHE KEY (prevents API spam)
    # ─────────────────────────────
    cache_key = f"eta_{origin_lat}_{origin_lng}_{dest_lat}_{dest_lng}"

    cached_eta = cache.get(cache_key)
    if cached_eta:
        return cached_eta

    # ─────────────────────────────
    # GOOGLE API REQUEST
    # ─────────────────────────────
    url = (
        "https://maps.googleapis.com/maps/api/directions/json"
        f"?origin={origin_lat},{origin_lng}"
        f"&destination={dest_lat},{dest_lng}"
        f"&key={GOOGLE_MAPS_API_KEY}"
    )

    try:
        response = requests.get(url, timeout=5)
        data = response.json()

        # ── SAFE VALIDATION
        if data.get("status") != "OK":
            return None

        route = data.get("routes", [])
        if not route:
            return None

        legs = route[0].get("legs", [])
        if not legs:
            return None

        duration_seconds = legs[0].get("duration", {}).get("value")

        if not duration_seconds:
            return None

        eta_minutes = max(1, round(duration_seconds / 60))

        # ─────────────────────────────
        # CACHE RESULT (5 minutes)
        # ─────────────────────────────
        cache.set(cache_key, eta_minutes, timeout=300)

        return eta_minutes

    except requests.RequestException:
        return None

    except Exception:
        return None
import requests
from decouple import config
from django.core.cache import cache

LOCATIONIQ_API_KEY = config('LOCATIONIQ_API_KEY', default='')


def get_locationiq_eta(origin_lat, origin_lng, dest_lat, dest_lng):
    """
    Returns real road ETA in minutes using LocationIQ's Directions API.
    Includes caching + safe fallback handling.
    """

    # ─────────────────────────────
    # CACHE KEY (prevents API spam)
    # ─────────────────────────────
    cache_key = f"eta_{origin_lat}_{origin_lng}_{dest_lat}_{dest_lng}"

    cached_eta = cache.get(cache_key)
    if cached_eta:
        return cached_eta

    if not LOCATIONIQ_API_KEY:
        return None

    # ─────────────────────────────
    # LOCATIONIQ DIRECTIONS REQUEST
    # Coordinate order is lon,lat (note: reversed from lat,lng)
    # ─────────────────────────────
    url = (
        f"https://us1.locationiq.com/v1/directions/driving/"
        f"{origin_lng},{origin_lat};{dest_lng},{dest_lat}"
        f"?key={LOCATIONIQ_API_KEY}&overview=false"
    )

    try:
        response = requests.get(url, timeout=5)
        data = response.json()

        # ── SAFE VALIDATION
        if data.get("code") != "Ok":
            return None

        routes = data.get("routes", [])
        if not routes:
            return None

        duration_seconds = routes[0].get("duration")
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


# ─────────────────────────────
# BACKWARD-COMPATIBLE ALIAS
# Some call sites may still import `get_google_eta` by its old name
# from before the LocationIQ switch — this keeps those imports working
# without needing to track down and edit every reference.
# ─────────────────────────────
get_google_eta = get_locationiq_eta
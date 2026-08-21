"""
rider/admin_notify.py
Sends a sound-alert notification to all admin/staff users when a new
rider application is submitted.

Channels used (in order of priority):
  1. Web Push (VAPID) — browser notification with alert sound
  2. SMS (Arkesel)    — fallback if no push subscription
  3. In-app           — always stored in admin notification table
"""
import logging
from django.conf import settings

log = logging.getLogger(__name__)


def notify_admins_new_rider(rider_profile):
    """
    Call this immediately after a new RiderProfile is created.
    Notifies all admin + staff users via push, SMS and in-app.
    """
    from django.contrib.auth import get_user_model
    User = get_user_model()

    rider_name  = rider_profile.rider.get_full_name() or rider_profile.rider.phone or "A rider"
    vehicle     = rider_profile.get_vehicle_type_display() if hasattr(rider_profile, 'get_vehicle_type_display') else rider_profile.vehicle_type
    title       = "🛵 New Rider Application"
    body        = f"{rider_name} applied ({vehicle}). Tap to review and verify."
    verify_url  = f"/admin/rider/riderprofile/?is_verified__exact=0"

    # ── 1. Web Push with sound ──────────────────────────────────────────────
    admins = User.objects.filter(role__in=['admin', 'staff'], is_active=True)
    for admin in admins:
        _send_push(admin, title, body, verify_url)

    # ── 2. SMS to admin phone ───────────────────────────────────────────────
    admin_phone = getattr(settings, 'ADMIN_PHONE', '')
    if admin_phone:
        try:
            from notifications.sms import send_sms
            send_sms(
                admin_phone,
                f"Lynctel: New rider application from {rider_name} ({vehicle}). "
                f"Verify at: lynctel.up.railway.app/admin/rider/riderprofile/"
            )
        except Exception as e:
            log.warning("SMS notify failed: %s", e)

    # ── 3. In-app notification (admin sees it in their notification panel) ──
    try:
        from rider.notification_model import RiderNotification
        for admin in admins:
            RiderNotification.objects.create(
                rider      = admin,
                title      = title,
                message    = body,
                link       = verify_url,
                notif_type = 'general',
            )
    except Exception as e:
        log.warning("In-app notify failed: %s", e)


def _send_push(user, title, body, url='/admin/'):
    """Send a Web Push notification with a sound alert."""
    try:
        from accounts.models import PushSubscription
        from pywebpush import webpush, WebPushException
        import json

        subs = PushSubscription.objects.filter(user=user, is_active=True)
        if not subs.exists():
            return

        private_key = getattr(settings, 'VAPID_PRIVATE_KEY', '')
        admin_email = getattr(settings, 'VAPID_ADMIN_EMAIL', '')
        if not private_key or not admin_email:
            log.warning("VAPID keys not configured — push not sent")
            return

        payload = json.dumps({
            "title":            title,
            "body":             body,
            "url":              url,
            "icon":             "/static/images/icon-192.png",
            "badge":            "/static/images/badge-72.png",
            "sound":            "alert",        # picked up by sw.js
            "requireInteraction": True,         # stays on screen until dismissed
            "tag":              "rider-application",
            "vibrate":          [200, 100, 200],
            "actions": [
                {"action": "verify", "title": "Verify Now"},
                {"action": "dismiss", "title": "Later"},
            ],
        })

        for sub in subs:
            try:
                webpush(
                    subscription_info = sub.to_dict(),
                    data              = payload,
                    vapid_private_key = private_key,
                    vapid_claims      = {"sub": f"mailto:{admin_email}"},
                )
            except WebPushException as e:
                log.warning("Push failed for %s: %s", user, e)
                if "410" in str(e) or "404" in str(e):
                    sub.is_active = False
                    sub.save(update_fields=['is_active'])
    except ImportError:
        log.warning("pywebpush not installed — Web Push unavailable")
    except Exception as e:
        log.warning("Push error: %s", e)
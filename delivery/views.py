"""
delivery/views.py

FIXES in this version:
  1. Imports from .utils (bridge) — no more ImportError crash
  2. update_rider_location — auth check: only the assigned rider can POST
  3. update_delivery_status — triggers SMS + push + rider payout on delivered
  4. DeliveryAcceptance rejection — auto-reassigns to next nearest rider
  5. track_delivery — passes correct context vars (no more TemplateSyntaxError)
"""
import json
import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.timezone import now
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from order.models import Order
from rider.models import DeliveryAcceptance, RiderProfile
from .models import Delivery, DeliveryTracking, DeliveryZone
from .utils import haversine_distance, calculate_distance, calculate_delivery_fee, estimate_eta_minutes

log = logging.getLogger(__name__)


# ── CREATE DELIVERY AFTER ORDER ────────────────────────────────────────────────

def create_delivery(order):
    zone = DeliveryZone.objects.filter(is_active=True).first()
    delivery, _ = Delivery.objects.get_or_create(
        order=order,
        defaults={'zone': zone, 'delivery_fee': zone.delivery_fee if zone else 0},
    )
    return delivery


# ── CUSTOMER TRACKING PAGE ─────────────────────────────────────────────────────

@login_required
def track_delivery(request, order_ref):
    delivery = get_object_or_404(
        Delivery.objects.select_related('order', 'rider__rider'),
        order__order_ref=order_ref,
    )

    if request.GET.get('live') == '1':
        return JsonResponse({
            'lat':    delivery.current_lat,
            'lng':    delivery.current_lng,
            'status': delivery.status,
        })

    # Build safe context — never use undefined variables in template
    customer_lat = (delivery.dropoff_lat
                    or getattr(delivery.order, 'delivery_lat', None)
                    or 5.6037)
    customer_lng = (delivery.dropoff_lng
                    or getattr(delivery.order, 'delivery_lng', None)
                    or -0.1870)

    rider_name  = ''
    rider_phone = ''
    if delivery.rider:
        rider_name  = delivery.rider.rider.get_full_name() or delivery.rider.rider.phone
        rider_phone = getattr(delivery.rider.rider, 'phone', '')

    return render(request, 'delivery/track.html', {
        'delivery':    delivery,
        'customer_lat': customer_lat,
        'customer_lng': customer_lng,
        'rider_name':  rider_name,
        'rider_phone': rider_phone,
    })


# ── RIDER DASHBOARD (delivery app legacy) ─────────────────────────────────────

@login_required
def rider_dashboard(request):
    deliveries = Delivery.objects.filter(
        rider__rider=request.user
    ).select_related('order').order_by('-created_at')[:20]
    return render(request, 'delivery/rider_dashboard.html', {
        'deliveries': deliveries,
    })


# ── UPDATE DELIVERY STATUS ─────────────────────────────────────────────────────

@login_required
@require_POST
def update_delivery_status(request, delivery_id, status):
    delivery = get_object_or_404(Delivery, id=delivery_id)

    # Only the assigned rider may update status
    if not delivery.rider or delivery.rider.rider != request.user:
        return redirect('rider:dashboard')

    valid = [s[0] for s in Delivery.Status.choices]
    if status not in valid:
        return redirect('rider:dashboard')

    delivery.status = status
    if status == Delivery.Status.PICKED_UP:
        delivery.picked_up_at = now()
    elif status == Delivery.Status.DELIVERED:
        delivery.delivered_at = now()
        # Mark rider available again
        delivery.rider.status = RiderProfile.Status.AVAILABLE
        delivery.rider.save(update_fields=['status'])
    delivery.save()

    # ── SMS + push to customer ────────────────────────────────────────────
    try:
        customer = None
        if delivery.order:
            customer = delivery.order.customer
        elif hasattr(delivery, 'food_order') and delivery.food_order:
            customer = delivery.food_order.customer

        if customer:
            _notify_customer_status_change(delivery, customer, status)
    except Exception as exc:
        log.error('[Delivery] Notification error after status change: %s', exc)

    # ── Rider payout (product orders) ─────────────────────────────────────
    if status == Delivery.Status.DELIVERED:
        try:
            _pay_rider_for_delivery(delivery)
        except Exception as exc:
            log.error('[Delivery] Rider payout error: %s', exc)

    # ── Real-time WebSocket push to tracking page ──────────────────────────
    try:
        channel_layer = get_channel_layer()
        async_to_sync(channel_layer.group_send)(
            f'delivery_{delivery.pk}',
            {'type': 'delivery_status', 'status': status},
        )
    except Exception:
        pass

    return redirect('rider:dashboard')


# ── GPS LOCATION UPDATE (authenticated, assigned rider only) ──────────────────

@login_required
@require_POST
def update_rider_location(request, delivery_id):
    """
    Receives GPS coordinates from the rider's phone.
    Only the rider assigned to this delivery may post.
    """
    delivery = get_object_or_404(Delivery, pk=delivery_id)

    # Security: must be the assigned rider
    if not delivery.rider or delivery.rider.rider != request.user:
        return JsonResponse({'error': 'Not your delivery'}, status=403)

    try:
        data = json.loads(request.body)
        lat  = float(data['lat'])
        lng  = float(data['lng'])
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
        return JsonResponse({'error': f'Invalid data: {e}'}, status=400)

    # Save current position
    delivery.current_lat = lat
    delivery.current_lng = lng
    delivery.save(update_fields=['current_lat', 'current_lng'])

    # Also update rider profile location
    try:
        from rider.models import RiderLocation
        RiderLocation.objects.update_or_create(
            rider=request.user,
            defaults={'latitude': lat, 'longitude': lng, 'is_active': True},
        )
    except Exception:
        pass

    # Track history
    DeliveryTracking.objects.create(delivery=delivery, latitude=lat, longitude=lng)

    # Push via WebSocket to customer tracking page
    try:
        channel_layer = get_channel_layer()
        async_to_sync(channel_layer.group_send)(
            f'delivery_{delivery_id}',
            {'type': 'send_location', 'lat': lat, 'lng': lng, 'status': delivery.status},
        )
    except Exception:
        pass

    return JsonResponse({'success': True, 'status': delivery.status})


# ── TRACKING DATA API ──────────────────────────────────────────────────────────

@login_required
def tracking_data(request, delivery_id):
    delivery = get_object_or_404(Delivery, pk=delivery_id)
    return JsonResponse({
        'lat':    delivery.current_lat,
        'lng':    delivery.current_lng,
        'status': delivery.status,
    })


# ── AUTO-ASSIGN NEAREST RIDER ──────────────────────────────────────────────────

@login_required
def assign_nearest_rider(request, delivery_id):
    delivery = get_object_or_404(Delivery, id=delivery_id)
    from .services import assign_rider_to_delivery
    rider = assign_rider_to_delivery(delivery)
    if not rider:
        return JsonResponse({'error': 'No available rider'})
    return JsonResponse({
        'success': True,
        'rider':   rider.rider.get_full_name() or rider.rider.phone,
    })


# ── BOOK A RIDE ────────────────────────────────────────────────────────────────

@login_required
def book_ride(request):
    zones = DeliveryZone.objects.filter(is_active=True)
    if request.method != 'POST':
        return render(request, 'delivery/book_ride.html', {'zones': zones})

    pickup  = request.POST.get('pickup_location', '').strip()
    dropoff = request.POST.get('dropoff_location', '').strip()
    if not pickup or not dropoff:
        messages.error(request, 'Pickup and dropoff are required.')
        return render(request, 'delivery/book_ride.html', {'zones': zones})

    def _float(val):
        try: return float(val) if val else None
        except (TypeError, ValueError): return None

    zone = DeliveryZone.objects.filter(
        pk=request.POST.get('zone_id'), is_active=True
    ).first()

    delivery = Delivery.objects.create(
        booker=request.user,
        pickup_location=pickup,
        dropoff_location=dropoff,
        pickup_lat=_float(request.POST.get('pickup_lat')),
        pickup_lng=_float(request.POST.get('pickup_lng')),
        dropoff_lat=_float(request.POST.get('dropoff_lat')),
        dropoff_lng=_float(request.POST.get('dropoff_lng')),
        zone=zone,
        delivery_type=Delivery.DeliveryType.EXPRESS,
        delivery_note=request.POST.get('note', ''),
        status=Delivery.Status.PENDING,
    )
    _auto_assign_and_notify(delivery)
    messages.success(request, "Ride booked! Finding a rider…")
    return redirect('delivery:track_ride', pk=delivery.pk)


# ── LIVE TRACKING (STANDALONE RIDE) ───────────────────────────────────────────

@login_required
def track_ride(request, pk):
    delivery = get_object_or_404(Delivery, pk=pk)
    is_rider  = delivery.rider and delivery.rider.rider == request.user
    is_booker = delivery.booker == request.user
    if not is_booker and not is_rider and request.user.role not in ('admin', 'staff'):
        messages.error(request, 'Access denied.')
        return redirect('frontend:home')

    customer_lat = delivery.dropoff_lat or 5.6037
    customer_lng = delivery.dropoff_lng or -0.1870
    return render(request, 'delivery/track_live.html', {
        'delivery':    delivery,
        'customer_lat': customer_lat,
        'customer_lng': customer_lng,
    })


# ── VENDOR ASSIGNS RIDER MANUALLY ─────────────────────────────────────────────

@login_required
@require_POST
def vendor_assign_rider(request, delivery_id, rider_id):
    delivery = get_object_or_404(Delivery, pk=delivery_id, status=Delivery.Status.PENDING)
    rider    = get_object_or_404(RiderProfile, pk=rider_id, status=RiderProfile.Status.AVAILABLE)

    acceptance, created = DeliveryAcceptance.objects.get_or_create(
        delivery=delivery,
        defaults={'rider': rider, 'status': DeliveryAcceptance.Status.PENDING},
    )
    if not created:
        acceptance.rider = rider
        acceptance.status = DeliveryAcceptance.Status.PENDING
        acceptance.responded_at = None
        acceptance.save()

    _push_prompt_to_rider(rider, delivery, acceptance)
    _notify_rider_in_db(rider.rider, delivery)

    return JsonResponse({'success': True, 'rider': rider.rider.get_full_name() or rider.rider.phone})


# ── PRICE ESTIMATE ─────────────────────────────────────────────────────────────

def price_estimate(request):
    try:
        dist = haversine_distance(
            float(request.GET['olat']), float(request.GET['olng']),
            float(request.GET['dlat']), float(request.GET['dlng']),
        )
        fee = calculate_delivery_fee(dist)
        eta = estimate_eta_minutes(dist)
        return JsonResponse({'success': True, 'distance_km': round(dist, 2),
                             'fee': str(fee), 'eta_minutes': eta})
    except (KeyError, TypeError, ValueError) as e:
        return JsonResponse({'success': False, 'error': str(e)})


# ── INTERNAL HELPERS ───────────────────────────────────────────────────────────

def _auto_assign_and_notify(delivery):
    from .services import assign_rider_to_delivery
    assign_rider_to_delivery(delivery, notify=True)


def _push_prompt_to_rider(rider_profile, delivery, acceptance):
    try:
        channel_layer = get_channel_layer()
        async_to_sync(channel_layer.group_send)(
            f'rider_{rider_profile.rider.id}',
            {
                'type':          'ride_request',
                'delivery_id':   delivery.pk,
                'acceptance_id': acceptance.pk,
                'pickup':        delivery.pickup_location or '',
                'dropoff':       delivery.dropoff_location or '',
                'fee':           str(delivery.delivery_fee),
                'commission':    str(delivery.calculate_commission()),
            },
        )
    except Exception as exc:
        log.warning('[Delivery] WebSocket push failed: %s', exc)


def _notify_rider_in_db(rider_user, delivery):
    try:
        from rider.views import notify_rider
        notify_rider(
            rider_user, 'New Delivery Request',
            f'Pickup: {delivery.pickup_location}  →  {delivery.dropoff_location}',
            notif_type='new_delivery', link='/rider/',
        )
    except Exception:
        pass


def _notify_customer_status_change(delivery, customer, status):
    """SMS + push notification to customer on delivery status change."""
    from notifications.sms import send_sms

    phone = ''
    if delivery.order:
        phone = delivery.order.delivery_phone
    elif hasattr(delivery, 'food_order') and delivery.food_order:
        phone = getattr(delivery.food_order, 'delivery_phone', '')

    order_ref = ''
    if delivery.order:
        order_ref = delivery.order.order_ref
    elif hasattr(delivery, 'food_order') and delivery.food_order:
        order_ref = getattr(delivery.food_order, 'order_ref', '')

    sms_map = {
        'picked_up': f'Lynctel: Your order {order_ref} has been picked up! '
                     f'Your rider is on the way.',
        'en_route':  f'Lynctel: Your order {order_ref} is en route to you. '
                     f'Rider will call on arrival.',
        'delivered': f'Lynctel: Your order {order_ref} has been delivered! '
                     f'Thank you for using Lynctel 🎉',
    }
    if phone and status in sms_map:
        send_sms(phone, sms_map[status])

    # Push notification
    try:
        from push_notify import send_push_notification
        push_map = {
            'picked_up': ('Order Picked Up 📦', f'{order_ref} is on the way!'),
            'delivered': ('Order Delivered 🎉', f'{order_ref} has arrived!'),
        }
        if status in push_map and customer:
            title, body = push_map[status]
            send_push_notification(customer, title, body)
    except Exception:
        pass


def _pay_rider_for_delivery(delivery):
    """
    Trigger Hubtel MoMo payout to rider (95% of delivery fee).
    Matches food/views.py _pay_rider_on_delivery() pattern.
    """
    if not delivery.rider:
        return
    from decimal import Decimal
    RIDER_SHARE = Decimal('0.95')
    delivery_fee = Decimal(str(delivery.delivery_fee or 0))
    rider_payout = (delivery_fee * RIDER_SHARE).quantize(Decimal('0.01'))

    rider_phone = (
        getattr(delivery.rider.rider, 'momo_number', None)
        or getattr(delivery.rider.rider, 'phone', None)
        or ''
    )
    if not rider_phone or rider_payout <= 0:
        log.warning('[Delivery] Rider payout skipped — no phone or zero amount')
        return

    try:
        from food.views import _hubtel_transfer
        order_ref = delivery.order.order_ref if delivery.order else str(delivery.pk)
        ok = _hubtel_transfer(
            phone=rider_phone,
            amount=rider_payout,
            reference=f'RIDER-PROD-{order_ref}',
            description=f'Lynctel rider payout {order_ref} — 95% of GHS {delivery_fee}',
        )
        if ok:
            # Record earning
            try:
                from rider.models import RiderEarning
                RiderEarning.objects.get_or_create(
                    delivery=delivery,
                    defaults={'rider': delivery.rider, 'amount': rider_payout, 'status': 'paid'},
                )
            except Exception:
                pass
        else:
            log.error('[Delivery] Rider Hubtel payout FAILED for %s — manual needed', order_ref)
    except ImportError:
        log.warning('[Delivery] _hubtel_transfer not available — payout skipped')

# ── ACCEPTANCE TIMEOUT CRON (item 5) ──────────────────────────────────────────
# Railway Cron: every minute → GET /delivery/timeout/?token=<CRON_TOKEN>
# Set Header: X-Cron-Token in Railway Cron settings

def acceptance_timeout(request):
    """
    Reassigns any DeliveryAcceptance pending > 60s without a rider response.
    Called by Railway Cron job every minute.
    """
    import logging
    from datetime import timedelta
    from django.conf import settings as _s
    from django.http import HttpResponse, JsonResponse
    from django.utils import timezone as _tz

    _log = logging.getLogger(__name__)

    # Verify cron token
    token = request.headers.get('X-Cron-Token', '')
    if token != getattr(_s, 'CRON_TOKEN', ''):
        return HttpResponse(status=401)

    from rider.models import DeliveryAcceptance
    from delivery.services import assign_rider_to_delivery

    cutoff      = _tz.now() - timedelta(seconds=60)
    stale       = DeliveryAcceptance.objects.filter(
        status=DeliveryAcceptance.Status.PENDING,
        created_at__lt=cutoff,
    ).select_related('delivery', 'rider')
    stale_count = stale.count()
    reassigned  = 0

    for acc in stale:
        acc.status       = DeliveryAcceptance.Status.REJECTED
        acc.responded_at = _tz.now()
        acc.save(update_fields=['status', 'responded_at'])
        try:
            assign_rider_to_delivery(acc.delivery, notify=True)
            reassigned += 1
            _log.info('[Timeout] Delivery %d reassigned after rider timeout', acc.delivery.pk)
        except Exception as exc:
            _log.error('[Timeout] Reassignment failed for delivery %d: %s', acc.delivery.pk, exc)

    return JsonResponse({'checked': stale_count, 'reassigned': reassigned})
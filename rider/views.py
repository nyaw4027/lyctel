"""
rider/views.py — Complete rider-facing views
"""
import json
import logging
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST, require_GET
from django.db.models import Sum, Count

from delivery.models import Delivery, DeliveryTracking, DeliveryZone
from rider.models import RiderProfile, RiderEarning, DeliveryAcceptance

log = logging.getLogger(__name__)


# ── Decorator ─────────────────────────────────────────────────────────────────

def rider_required(view_func):
    """Ensures user has an approved RiderProfile."""
    @login_required
    def wrapper(request, *args, **kwargs):
        # Query DB directly — never use cached related_name accessor
        # This prevents stale is_verified=False after admin approves the rider
        try:
            profile = RiderProfile.objects.get(rider=request.user)
        except RiderProfile.DoesNotExist:
            return redirect('rider:apply')
        if not profile.is_verified:
            return redirect('rider:pending')
        request.rider_profile = profile
        return view_func(request, *args, **kwargs)
    wrapper.__name__ = view_func.__name__
    return wrapper


# ── Application ────────────────────────────────────────────────────────────────

@login_required
def apply(request):
    """Rider application form."""
    # Already a rider — check DB directly
    try:
        profile = RiderProfile.objects.get(rider=request.user)
        if profile.is_verified:
            return redirect('rider:dashboard')
        return redirect('rider:pending')
    except RiderProfile.DoesNotExist:
        pass

    if request.method == 'POST':
        vehicle_type  = request.POST.get('vehicle_type', '').strip()
        vehicle_plate = request.POST.get('vehicle_plate', '').strip()
        zone_id       = request.POST.get('zone', '')
        id_card       = request.FILES.get('id_card')

        if not vehicle_type:
            messages.error(request, 'Please select a vehicle type.')
        else:
            zone = None
            if zone_id:
                try:
                    zone = DeliveryZone.objects.get(pk=zone_id)
                except DeliveryZone.DoesNotExist:
                    pass

            profile = RiderProfile.objects.create(
                rider         = request.user,
                vehicle_type  = vehicle_type,
                vehicle_plate = vehicle_plate,
                zone          = zone,
                id_card       = id_card,
                status        = RiderProfile.Status.OFFLINE,
                is_verified   = False,
            )
            # Notify all admin/staff users with sound alert
            try:
                from rider.admin_notify import notify_admins_new_rider
                notify_admins_new_rider(profile)
            except Exception:
                pass
            messages.success(request, 'Application submitted! We\'ll review and get back to you soon.')
            return redirect('rider:pending')

    zones = DeliveryZone.objects.filter(is_active=True)
    return render(request, 'rider/apply.html', {'zones': zones})


@login_required
def pending(request):
    """Waiting for approval page."""
    try:
        profile = RiderProfile.objects.get(rider=request.user)
    except RiderProfile.DoesNotExist:
        return redirect('rider:apply')
    # If already verified — go straight to dashboard
    if profile.is_verified:
        return redirect('rider:dashboard')
    return render(request, 'rider/pending.html', {'profile': profile})


# ── Dashboard ──────────────────────────────────────────────────────────────────

@rider_required
def dashboard(request):
    profile = request.rider_profile
    today   = timezone.now().date()

    # Active delivery
    active_delivery = Delivery.objects.filter(
        rider=profile,
        status__in=['assigned', 'picked_up', 'en_route']
    ).select_related('order', 'order__customer').first()

    # Pending (offered but not yet accepted)
    pending_deliveries = Delivery.objects.filter(
        rider=profile,
        status='pending'
    ).select_related('order', 'order__customer').order_by('created_at')

    # Today stats
    today_qs       = Delivery.objects.filter(rider=profile, delivered_at__date=today)
    today_count    = today_qs.count()
    today_earnings = today_qs.aggregate(t=Sum('rider_commission'))['t'] or 0

    # Recent deliveries
    recent_deliveries = Delivery.objects.filter(
        rider=profile
    ).select_related('order', 'order__customer').order_by('-created_at')[:20]

    # Notifications
    try:
        from rider.notification_model import RiderNotification
        unread_count  = RiderNotification.objects.filter(rider=request.user, is_read=False).count()
        notifications = RiderNotification.objects.filter(rider=request.user).order_by('-created_at')[:10]
    except Exception:
        unread_count  = 0
        notifications = []

    return render(request, 'rider/dashboard.html', {
        'profile':            profile,
        'active_delivery':    active_delivery,
        'pending_deliveries': pending_deliveries,
        'today_count':        today_count,
        'today_earnings':     today_earnings,
        'recent_deliveries':  recent_deliveries,
        'unread_count':       unread_count,
        'notifications':      notifications,
    })


# ── Status toggle ──────────────────────────────────────────────────────────────

@rider_required
@require_POST
def toggle_status(request):
    profile    = request.rider_profile
    new_status = request.POST.get('status', '')
    valid      = [s[0] for s in RiderProfile.Status.choices]
    if new_status in valid:
        profile.status = new_status
        profile.save(update_fields=['status'])
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'success': True, 'status': profile.status})
    return redirect('rider:dashboard')


# ── Accept / Reject ────────────────────────────────────────────────────────────

@rider_required
@require_POST
def accept_delivery(request, pk):
    delivery = get_object_or_404(Delivery, pk=pk, rider=request.rider_profile)
    if delivery.status == 'pending':
        delivery.set_status('assigned')
        # Update acceptance record
        DeliveryAcceptance.objects.filter(
            delivery=delivery, rider=request.rider_profile
        ).update(status='accepted', responded_at=timezone.now())
        # Notify customer
        try:
            from notifications.sms import sms_rider_assigned
            if delivery.order:
                sms_rider_assigned(delivery.order, delivery)
        except Exception:
            pass
        messages.success(request, 'Delivery accepted! Head to the pickup location.')
    return redirect('rider:dashboard')


@rider_required
@require_POST
def reject_delivery(request, pk):
    delivery = get_object_or_404(Delivery, pk=pk, rider=request.rider_profile)
    if delivery.status == 'pending':
        DeliveryAcceptance.objects.filter(
            delivery=delivery, rider=request.rider_profile
        ).update(status='rejected', responded_at=timezone.now())
        delivery.rider  = None
        delivery.status = 'pending'
        delivery.save(update_fields=['rider', 'status'])
        # Try to assign another rider
        try:
            from delivery.services import assign_rider_to_delivery
            assign_rider_to_delivery(delivery, notify=True)
        except Exception:
            pass
    return redirect('rider:dashboard')


# ── Live map ───────────────────────────────────────────────────────────────────

@rider_required
def live_map(request, pk):
    delivery = get_object_or_404(
        Delivery.objects.select_related('order', 'order__customer'),
        pk=pk, rider=request.rider_profile
    )
    return render(request, 'rider/live_map.html', {
        'delivery':    delivery,
        'profile':     request.rider_profile,
        'CSRF_TOKEN':  request.META.get('CSRF_COOKIE', ''),
    })


# ── Update delivery status ─────────────────────────────────────────────────────

@rider_required
@require_POST
def update_delivery(request, pk):
    delivery   = get_object_or_404(Delivery, pk=pk, rider=request.rider_profile)
    new_status = request.POST.get('status', '').strip()
    valid      = [s[0] for s in Delivery.Status.choices]

    if new_status not in valid:
        messages.error(request, 'Invalid status.')
        return redirect('rider:dashboard')

    old_status = delivery.status
    delivery.set_status(new_status)

    # On delivery completion
    if new_status == 'delivered' and old_status != 'delivered':
        # Record commission split — customer paid rider directly
        payment_method = request.POST.get('payment_method', 'cash')
        try:
            from rider.ledger_service import record_delivery_commission
            record_delivery_commission(delivery, payment_method=payment_method)
        except Exception as e:
            log.warning("Ledger entry failed: %s", e)

        # Legacy payout (if applicable)
        try:
            from delivery.services import pay_rider_for_delivery
            pay_rider_for_delivery(delivery)
        except Exception:
            pass

        # SMS customer
        try:
            from notifications.sms import sms_order_delivered
            if delivery.order:
                sms_order_delivered(delivery.order)
        except Exception:
            pass

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'success': True, 'status': new_status})
    messages.success(request, f'Status updated to {delivery.get_status_display()}')
    return redirect('rider:dashboard')


# ── Location update ────────────────────────────────────────────────────────────

@rider_required
@require_POST
def update_location(request):
    profile = request.rider_profile
    try:
        data = json.loads(request.body)
        lat  = float(data.get('lat') or data.get('latitude'))
        lng  = float(data.get('lng') or data.get('longitude'))
    except Exception:
        lat = request.POST.get('lat') or request.POST.get('latitude')
        lng = request.POST.get('lng') or request.POST.get('longitude')
        try:
            lat = float(lat)
            lng = float(lng)
        except Exception:
            return JsonResponse({'error': 'Invalid coordinates'}, status=400)

    # Update profile GPS
    profile.current_lat = lat
    profile.current_lng = lng
    profile.save(update_fields=['current_lat', 'current_lng'])

    # Update active delivery tracking
    active = Delivery.objects.filter(
        rider=profile,
        status__in=['assigned', 'picked_up', 'en_route']
    ).first()
    if active:
        active.add_tracking(lat, lng)
        # Broadcast via WebSocket
        try:
            from channels.layers import get_channel_layer
            from asgiref.sync import async_to_sync
            layer = get_channel_layer()
            async_to_sync(layer.group_send)(
                f'delivery_{active.pk}',
                {'type': 'location_update', 'lat': lat, 'lng': lng}
            )
        except Exception:
            pass

    return JsonResponse({'success': True, 'lat': lat, 'lng': lng})


# ── Location API ───────────────────────────────────────────────────────────────

@require_GET
def location_api(request, order_ref):
    """Customer-facing: get rider's current location for tracking."""
    try:
        delivery = Delivery.objects.select_related('rider').get(
            order__order_ref=order_ref
        )
    except Delivery.DoesNotExist:
        return JsonResponse({'error': 'Not found'}, status=404)

    rider = delivery.rider
    if not rider or delivery.current_lat is None:
        return JsonResponse({'available': False})

    return JsonResponse({
        'available': True,
        'lat':       delivery.current_lat,
        'lng':       delivery.current_lng,
        'status':    delivery.status,
    })


# ── ETA API ────────────────────────────────────────────────────────────────────

@require_GET
def eta_api(request):
    """Returns ETA estimate based on current rider location."""
    try:
        from delivery.services import calculate_distance
        lat1 = float(request.GET['lat'])
        lng1 = float(request.GET['lng'])
        lat2 = float(request.GET['dest_lat'])
        lng2 = float(request.GET['dest_lng'])
        dist = calculate_distance(lat1, lng1, lat2, lng2)
        eta  = max(5, int(dist * 3))   # ~3 min/km in Accra traffic
        return JsonResponse({'distance_km': round(dist, 2), 'eta_minutes': eta})
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)


# ── Notifications ──────────────────────────────────────────────────────────────

@rider_required
@require_POST
def notif_read(request, pk):
    try:
        from rider.notification_model import RiderNotification
        n = get_object_or_404(RiderNotification, pk=pk, rider=request.user)
        n.is_read = True
        n.save(update_fields=['is_read'])
    except Exception:
        pass
    return JsonResponse({'success': True})


@rider_required
@require_POST
def notif_read_all(request):
    try:
        from rider.notification_model import RiderNotification
        RiderNotification.objects.filter(rider=request.user, is_read=False).update(is_read=True)
    except Exception:
        pass
    return JsonResponse({'success': True})


@rider_required
@require_GET
def notif_count(request):
    try:
        from rider.notification_model import RiderNotification
        count = RiderNotification.objects.filter(rider=request.user, is_read=False).count()
    except Exception:
        count = 0
    return JsonResponse({'count': count})


# ── Earnings ───────────────────────────────────────────────────────────────────

@rider_required
def earnings(request):
    profile     = request.rider_profile
    now         = timezone.now()
    today       = now.date()
    week_start  = today - timezone.timedelta(days=today.weekday())
    month_start = today.replace(day=1)

    base_qs = Delivery.objects.filter(rider=profile, status='delivered')

    def stats(qs):
        agg = qs.aggregate(total=Sum('rider_commission'), count=Count('id'))
        return {'total': float(agg['total'] or 0), 'count': agg['count'] or 0}

    today_stats  = stats(base_qs.filter(delivered_at__date=today))
    week_stats   = stats(base_qs.filter(delivered_at__date__gte=week_start))
    month_stats  = stats(base_qs.filter(delivered_at__date__gte=month_start))
    all_stats    = stats(base_qs)

    # 30-day chart data
    chart_data = []
    for i in range(29, -1, -1):
        day = today - timezone.timedelta(days=i)
        amt = base_qs.filter(delivered_at__date=day).aggregate(
            t=Sum('rider_commission'))['t'] or 0
        chart_data.append({'date': str(day), 'amount': float(amt)})

    recent = base_qs.select_related(
        'order', 'order__customer'
    ).order_by('-delivered_at')[:30]

    return render(request, 'rider/earnings.html', {
        'profile':     profile,
        'today_stats': today_stats,
        'week_stats':  week_stats,
        'month_stats': month_stats,
        'all_stats':   all_stats,
        'chart_data':  chart_data,
        'recent':      recent,
    })

# ── Notify rider (used by delivery, staff, vendor, dashboard) ──────────────────

def notify_rider(rider_user, title, message, link='', notif_type='general'):
    """
    Create a RiderNotification and optionally send a push notification.
    Called from: delivery/services.py, delivery/views.py,
                 dashboard/views.py, staff/views.py, vendors/views.py
    """
    try:
        from rider.notification_model import RiderNotification
        RiderNotification.objects.create(
            rider      = rider_user,
            title      = title,
            message    = message,
            link       = link,
            notif_type = notif_type,
        )
    except Exception:
        pass

    # Push notification (non-blocking)
    try:
        from push_notify import send_push_notification
        send_push_notification(rider_user, title=title, body=message, url=link)
    except Exception:
        pass


def staff_only(view_func):
    @login_required
    def wrapper(request, *args, **kwargs):
        if request.user.role not in ('admin', 'staff'):
            return redirect('frontend:home')
        return view_func(request, *args, **kwargs)
    wrapper.__name__ = view_func.__name__
    return wrapper


@staff_only
def admin_balances(request):
    """
    Admin view: all rider balances — who owes what.
    URL: /rider/admin/balances/
    """
    from rider.models import RiderBalanceSummary
    from rider.models import RiderProfile

    balances = (
        RiderBalanceSummary.objects
        .select_related('rider', 'rider__rider')
        .order_by('-outstanding')
    )
    total_outstanding = sum(b.outstanding for b in balances)

    return render(request, 'rider/admin_balances.html', {
        'balances':         balances,
        'total_outstanding': total_outstanding,
    })


@staff_only
def rider_ledger_detail(request, rider_pk):
    """
    Admin: full ledger for one rider.
    URL: /rider/admin/balances/<int:rider_pk>/
    """
    from rider.models import RiderProfile
    from rider.models import RiderLedgerEntry, RiderBalanceSummary

    rider_profile = get_object_or_404(RiderProfile, pk=rider_pk)
    entries = (
        RiderLedgerEntry.objects
        .filter(rider=rider_profile)
        .select_related('delivery', 'delivery__order', 'settled_by')
        .order_by('-created_at')
    )
    try:
        balance = rider_profile.balance
    except Exception:
        from rider.models import RiderBalanceSummary
        balance, _ = RiderBalanceSummary.objects.get_or_create(rider=rider_profile)

    return render(request, 'rider/ledger_detail.html', {
        'rider_profile': rider_profile,
        'entries':       entries,
        'balance':       balance,
    })


@staff_only
@require_POST
def settle_rider_balance(request, rider_pk):
    """
    POST: mark one or all entries as settled.
    URL: /rider/admin/balances/<int:rider_pk>/settle/
    Body: entry_id=<uuid> (single) OR settle_all=1 (all outstanding)
    """
    from rider.models import RiderProfile
    from rider.ledger_service import settle_entry, settle_all_for_rider
    from rider.models import RiderLedgerEntry

    rider_profile = get_object_or_404(RiderProfile, pk=rider_pk)
    note          = request.POST.get('note', '')

    if request.POST.get('settle_all'):
        count = settle_all_for_rider(rider_profile, request.user, note)
        msg = f'Settled {count} entries for {rider_profile}'
    else:
        entry_id = request.POST.get('entry_id')
        entry    = get_object_or_404(RiderLedgerEntry, id=entry_id, rider=rider_profile)
        settle_entry(entry, request.user, note)
        msg = f'Entry settled — GHS {entry.app_commission}'

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'success': True, 'message': msg})

    from django.contrib import messages as dj_messages
    dj_messages.success(request, msg)
    return redirect('rider:ledger_detail', rider_pk=rider_pk)


@rider_required
def my_balance(request):
    """
    Rider view: see their own balance / what they owe the app.
    URL: /rider/balance/
    """
    from rider.models import RiderLedgerEntry, RiderBalanceSummary
    profile = request.rider_profile

    try:
        balance = profile.balance
    except Exception:
        from rider.models import RiderBalanceSummary
        balance, _ = RiderBalanceSummary.objects.get_or_create(rider=profile)

    entries = (
        RiderLedgerEntry.objects
        .filter(rider=profile)
        .select_related('delivery', 'delivery__order')
        .order_by('-created_at')[:20]
    )

    return render(request, 'rider/my_balance.html', {
        'profile': profile,
        'balance': balance,
        'entries': entries,
    })
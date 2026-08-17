"""
rider/views.py — complete rewrite

Covers every URL in rider/urls.py:
  apply, pending, dashboard, toggle_status,
  accept_delivery, reject_delivery, live_map,
  update_delivery, update_location, rider_location_api,
  eta_api, notification_read, notification_read_all,
  notification_count, rider_earnings
"""
import json
import logging
from datetime import timedelta
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import DeliveryAcceptance, RiderEarning, RiderLocation, RiderProfile
from delivery.models import Delivery

log = logging.getLogger(__name__)


# ── DECORATORS ─────────────────────────────────────────────────────────────────

def rider_required(view_func):
    """Guard: user must be an active, verified rider."""
    @login_required
    def wrapper(request, *args, **kwargs):
        try:
            profile = request.user.rider_profile
        except RiderProfile.DoesNotExist:
            messages.info(request, 'Apply to become a rider first.')
            return redirect('rider:apply')
        if not profile.is_verified:
            return redirect('rider:pending')
        request.rider = profile
        return view_func(request, *args, **kwargs)
    wrapper.__name__ = view_func.__name__
    return wrapper


# ── APPLY ──────────────────────────────────────────────────────────────────────

def apply(request):
    if request.user.is_authenticated:
        try:
            profile = request.user.rider_profile
            if profile.is_verified:
                return redirect('rider:dashboard')
            return redirect('rider:pending')
        except RiderProfile.DoesNotExist:
            pass

    errors    = {}
    form_data = {}

    if request.method == 'POST':
        form_data = request.POST.dict()

        vehicle_type  = request.POST.get('vehicle_type', '').strip()
        vehicle_plate = request.POST.get('vehicle_plate', '').strip()

        if not vehicle_type:
            errors['vehicle_type'] = 'Vehicle type is required.'

        if not request.user.is_authenticated:
            first_name = request.POST.get('first_name', '').strip()
            phone      = request.POST.get('phone', '').strip()
            password   = request.POST.get('password', '').strip()
            if not first_name: errors['first_name'] = 'First name is required.'
            if not phone:       errors['phone']      = 'Phone number is required.'
            if not password or len(password) < 6:
                errors['password'] = 'Password must be at least 6 characters.'

        if not errors:
            user = request.user
            if not user.is_authenticated:
                from django.contrib.auth import get_user_model, login
                User = get_user_model()
                if User.objects.filter(phone=phone).exists():
                    errors['phone'] = 'An account with this phone already exists.'
                else:
                    user = User.objects.create_user(
                        phone=phone, password=password,
                        first_name=first_name,
                        last_name=request.POST.get('last_name', '').strip(),
                        role='rider',
                    )
                    login(request, user)

            if not errors:
                profile, _ = RiderProfile.objects.get_or_create(rider=user)
                profile.vehicle_type  = vehicle_type
                profile.vehicle_plate = vehicle_plate
                profile.status        = RiderProfile.Status.OFFLINE
                if 'id_card' in request.FILES:
                    profile.id_card = request.FILES['id_card']
                profile.save()
                messages.success(request, 'Application submitted! We will review within 24 hours.')
                return redirect('rider:pending')

    return render(request, 'rider/apply.html', {
        'errors':    errors,
        'form_data': form_data,
        'cart_count': 0,
    })


# ── PENDING ────────────────────────────────────────────────────────────────────

@login_required
def pending(request):
    try:
        profile = request.user.rider_profile
        if profile.is_verified:
            return redirect('rider:dashboard')
    except RiderProfile.DoesNotExist:
        return redirect('rider:apply')
    return render(request, 'rider/pending.html', {'cart_count': 0})


# ── DASHBOARD ──────────────────────────────────────────────────────────────────

@rider_required
def dashboard(request):
    profile = request.rider

    # Active deliveries
    active = Delivery.objects.filter(
        rider=profile,
        status__in=[
            Delivery.Status.ASSIGNED,
            Delivery.Status.PICKED_UP,
            Delivery.Status.EN_ROUTE,
        ],
    ).select_related('order').order_by('-assigned_at')

    # Pending acceptance requests
    pending_requests = DeliveryAcceptance.objects.filter(
        rider=profile,
        status=DeliveryAcceptance.Status.PENDING,
    ).select_related('delivery').order_by('-created_at')

    # Completed today
    today = timezone.now().date()
    completed_today = Delivery.objects.filter(
        rider=profile,
        status=Delivery.Status.DELIVERED,
        delivered_at__date=today,
    ).count()

    # Unread notification count
    notif_count = _unread_count(request.user)

    # Earnings today
    earnings_today = Delivery.objects.filter(
        rider=profile,
        status=Delivery.Status.DELIVERED,
        delivered_at__date=today,
    ).aggregate(t=Sum('rider_commission'))['t'] or 0

    return render(request, 'rider/dashboard.html', {
        'profile':         profile,
        'active':          active,
        'pending_requests': pending_requests,
        'completed_today': completed_today,
        'earnings_today':  earnings_today,
        'notif_count':     notif_count,
        'cart_count':      0,
    })


# ── TOGGLE ONLINE/OFFLINE STATUS ───────────────────────────────────────────────

@rider_required
@require_POST
def toggle_status(request):
    profile = request.rider
    if profile.status == RiderProfile.Status.OFFLINE:
        profile.status = RiderProfile.Status.AVAILABLE
    elif profile.status == RiderProfile.Status.AVAILABLE:
        profile.status = RiderProfile.Status.OFFLINE
    # Do NOT toggle if ON_DELIVERY — let delivery completion handle that
    profile.save(update_fields=['status'])
    return JsonResponse({'status': profile.status, 'label': profile.get_status_display()})


# ── ACCEPT DELIVERY ────────────────────────────────────────────────────────────

@rider_required
@require_POST
def accept_delivery(request, pk):
    acceptance = get_object_or_404(
        DeliveryAcceptance,
        pk=pk,
        rider=request.rider,
        status=DeliveryAcceptance.Status.PENDING,
    )
    delivery = acceptance.delivery

    acceptance.status       = DeliveryAcceptance.Status.ACCEPTED
    acceptance.responded_at = timezone.now()
    acceptance.save()

    delivery.rider       = request.rider
    delivery.status      = Delivery.Status.ASSIGNED
    delivery.assigned_at = timezone.now()
    delivery.save(update_fields=['rider', 'status', 'assigned_at'])

    request.rider.status = RiderProfile.Status.ON_DELIVERY
    request.rider.save(update_fields=['status'])

    messages.success(request, 'Delivery accepted! Head to the pickup location.')
    return redirect('rider:live_map', pk=delivery.pk)


# ── REJECT DELIVERY ────────────────────────────────────────────────────────────

@rider_required
@require_POST
def reject_delivery(request, pk):
    acceptance = get_object_or_404(
        DeliveryAcceptance,
        pk=pk,
        rider=request.rider,
        status=DeliveryAcceptance.Status.PENDING,
    )
    acceptance.status       = DeliveryAcceptance.Status.REJECTED
    acceptance.responded_at = timezone.now()
    acceptance.save()

    # Auto-reassign to next nearest rider
    try:
        from delivery.services import assign_rider_to_delivery
        assign_rider_to_delivery(acceptance.delivery, notify=True)
        log.info('[Rider] Delivery %d rejected by %s — reassigned',
                 acceptance.delivery.pk, request.user)
    except Exception as exc:
        log.error('[Rider] Reassignment after rejection failed: %s', exc)

    messages.info(request, 'Delivery rejected. We will find another rider.')
    return redirect('rider:dashboard')


# ── LIVE MAP ───────────────────────────────────────────────────────────────────

@rider_required
def live_map(request, pk):
    delivery = get_object_or_404(
        Delivery.objects.select_related('order', 'rider__rider'),
        pk=pk, rider=request.rider,
    )
    # Safely get customer coordinates
    customer_lat = (
        getattr(delivery, 'dropoff_lat', None)
        or (getattr(delivery.order, 'delivery_lat', None) if delivery.order else None)
        or 5.6037
    )
    customer_lng = (
        getattr(delivery, 'dropoff_lng', None)
        or (getattr(delivery.order, 'delivery_lng', None) if delivery.order else None)
        or -0.1870
    )
    customer_address = ''
    customer_phone   = ''
    if delivery.order:
        customer_address = delivery.order.delivery_address or ''
        customer_phone   = delivery.order.delivery_phone   or ''

    return render(request, 'rider/delivery_detail.html', {
        'delivery':         delivery,
        'customer_lat':     customer_lat,
        'customer_lng':     customer_lng,
        'customer_address': customer_address,
        'customer_phone':   customer_phone,
        'cart_count':       0,
    })


# ── UPDATE DELIVERY STATUS ─────────────────────────────────────────────────────

@rider_required
@require_POST
def update_delivery(request, pk):
    delivery = get_object_or_404(Delivery, pk=pk, rider=request.rider)
    new_status = request.POST.get('status', '').strip()
    valid = [s[0] for s in Delivery.Status.choices]
    if new_status not in valid:
        messages.error(request, 'Invalid status.')
        return redirect('rider:live_map', pk=pk)

    delivery.set_status(new_status)

    if new_status == Delivery.Status.DELIVERED:
        request.rider.status = RiderProfile.Status.AVAILABLE
        request.rider.save(update_fields=['status'])
        # Trigger payout via delivery views
        try:
            from delivery.views import _pay_rider_for_delivery, _notify_customer_status_change
            _pay_rider_for_delivery(delivery)
            if delivery.order:
                _notify_customer_status_change(delivery, delivery.order.customer, new_status)
        except Exception as exc:
            log.error('[Rider] Post-delivery actions failed: %s', exc)

    return redirect('rider:dashboard')


# ── GPS UPDATE ─────────────────────────────────────────────────────────────────

@login_required
@require_POST
def update_location(request):
    """Rider sends GPS coordinates. Used while on delivery."""
    try:
        profile = request.user.rider_profile
    except RiderProfile.DoesNotExist:
        return JsonResponse({'error': 'Not a rider'}, status=403)

    try:
        data = json.loads(request.body)
        lat  = float(data['lat'])
        lng  = float(data['lng'])
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
        return JsonResponse({'error': str(e)}, status=400)

    # Update profile
    profile.current_lat = lat
    profile.current_lng = lng
    profile.save(update_fields=['current_lat', 'current_lng'])

    # Update location table
    RiderLocation.objects.update_or_create(
        rider=request.user,
        defaults={'latitude': lat, 'longitude': lng, 'is_active': True},
    )

    # Push to active delivery's WebSocket group
    active_delivery = Delivery.objects.filter(
        rider=profile,
        status__in=[Delivery.Status.ASSIGNED, Delivery.Status.PICKED_UP, Delivery.Status.EN_ROUTE],
    ).first()

    if active_delivery:
        try:
            from asgiref.sync import async_to_sync
            from channels.layers import get_channel_layer
            channel_layer = get_channel_layer()
            async_to_sync(channel_layer.group_send)(
                f'delivery_{active_delivery.pk}',
                {'type': 'send_location', 'lat': lat, 'lng': lng,
                 'status': active_delivery.status},
            )
        except Exception:
            pass

    return JsonResponse({'success': True})


# ── RIDER LOCATION API (customer polls this) ───────────────────────────────────

@login_required
def rider_location_api(request, order_ref):
    from order.models import Order as ProductOrder
    delivery = None
    # Try product order
    try:
        order    = ProductOrder.objects.get(order_ref=order_ref, customer=request.user)
        delivery = order.delivery
    except Exception:
        pass
    # Try food order
    if not delivery:
        try:
            from food.models import FoodOrder
            food_order = FoodOrder.objects.get(order_ref=order_ref, customer=request.user)
            delivery   = food_order.delivery
        except Exception:
            pass

    if not delivery or not delivery.rider:
        return JsonResponse({'available': False})

    try:
        loc = RiderLocation.objects.get(rider=delivery.rider.rider, is_active=True)
        return JsonResponse({
            'available': True,
            'lat':       float(loc.latitude),
            'lng':       float(loc.longitude),
            'status':    delivery.status,
        })
    except RiderLocation.DoesNotExist:
        return JsonResponse({'available': False, 'status': delivery.status})


# ── ETA API ────────────────────────────────────────────────────────────────────

@login_required
def eta_api(request):
    from delivery.utils import haversine_distance, estimate_eta_minutes
    try:
        rlat = float(request.GET['rlat'])
        rlng = float(request.GET['rlng'])
        dlat = float(request.GET['dlat'])
        dlng = float(request.GET['dlng'])
        dist = haversine_distance(rlat, rlng, dlat, dlng)
        return JsonResponse({'eta_minutes': estimate_eta_minutes(dist),
                             'distance_km': round(dist, 2)})
    except (KeyError, TypeError, ValueError) as e:
        return JsonResponse({'error': str(e)}, status=400)


# ── EARNINGS ───────────────────────────────────────────────────────────────────

@rider_required
def rider_earnings(request):
    profile = request.rider
    now     = timezone.now()
    week_start  = now - timedelta(days=7)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    base_qs = Delivery.objects.filter(rider=profile, status=Delivery.Status.DELIVERED)

    total_earnings  = base_qs.aggregate(t=Sum('rider_commission'))['t'] or 0
    total_deliveries= base_qs.count()
    week_earnings   = base_qs.filter(delivered_at__gte=week_start).aggregate(t=Sum('rider_commission'))['t'] or 0
    week_deliveries = base_qs.filter(delivered_at__gte=week_start).count()
    month_earnings  = base_qs.filter(delivered_at__gte=month_start).aggregate(t=Sum('rider_commission'))['t'] or 0

    pending_payout = RiderEarning.objects.filter(
        rider=profile, status=RiderEarning.Status.PENDING
    ).aggregate(t=Sum('amount'))['t'] or 0

    paid_out = RiderEarning.objects.filter(
        rider=profile, status=RiderEarning.Status.PAID
    ).aggregate(t=Sum('amount'))['t'] or 0

    recent = base_qs.order_by('-delivered_at')[:20]

    return render(request, 'rider/earnings.html', {
        'profile':          profile,
        'total_earnings':   total_earnings,
        'total_deliveries': total_deliveries,
        'week_earnings':    week_earnings,
        'week_deliveries':  week_deliveries,
        'month_earnings':   month_earnings,
        'pending_payout':   pending_payout,
        'paid_out':         paid_out,
        'recent':           recent,
        'cart_count':       0,
    })


# ── NOTIFICATIONS ──────────────────────────────────────────────────────────────

def notify_rider(rider_user, title, message, notif_type='info', link='/rider/'):
    """
    Create an in-app notification for a rider.
    Tries the chat.Notification model; silently skips if it doesn't exist.
    """
    try:
        from chat.models import Notification
        Notification.objects.create(
            user=rider_user, title=title, body=message,
            notif_type=notif_type, link=link,
        )
    except Exception:
        pass


@login_required
def notification_read(request, pk):
    try:
        from chat.models import Notification
        notif = get_object_or_404(Notification, pk=pk, user=request.user)
        notif.is_read = True
        notif.save(update_fields=['is_read'])
    except Exception:
        pass
    return JsonResponse({'success': True})


@login_required
def notification_read_all(request):
    try:
        from chat.models import Notification
        Notification.objects.filter(user=request.user, is_read=False).update(is_read=True)
    except Exception:
        pass
    return JsonResponse({'success': True})


@login_required
def notification_count(request):
    return JsonResponse({'count': _unread_count(request.user)})


def _unread_count(user):
    try:
        from chat.models import Notification
        return Notification.objects.filter(user=user, is_read=False).count()
    except Exception:
        return 0
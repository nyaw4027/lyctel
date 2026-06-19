from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.db.models import Sum
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from datetime import timedelta

from delivery.models import Delivery
from rider.models import RiderProfile, RiderEarning, RiderLocation, DeliveryAcceptance
from .notification_model import RiderNotification
from ecommerce.models import User


import json
import urllib.request
import urllib.parse
from rider.utils import get_google_eta


# ─────────────────────────────
# AUTH GUARD
# ─────────────────────────────
def rider_required(view_func):
    @login_required
    def wrapper(request, *args, **kwargs):
        if request.user.role != 'rider':
            messages.error(request, 'Access denied. Rider account required.')
            return redirect('frontend:home')
        # Auto-create the profile if it was never created
        profile, _ = RiderProfile.objects.get_or_create(rider=request.user)
        request.rider_profile = profile
        return view_func(request, *args, **kwargs)
    wrapper.__name__ = view_func.__name__
    return wrapper


# ─────────────────────────────
# APPLY TO BECOME A RIDER
# ─────────────────────────────
def apply(request):
    """
    Public page — anyone can apply.
    If already logged in with rider role, redirect to dashboard.
    If already applied (profile exists), redirect to pending.
    """
    if request.user.is_authenticated and request.user.role == 'rider':
        return redirect('rider:dashboard')

    if request.method == 'POST':
        vehicle_type  = request.POST.get('vehicle_type', '').strip()
        vehicle_plate = request.POST.get('vehicle_plate', '').strip()
        errors = {}

        if not vehicle_type:
            errors['vehicle_type'] = 'Please select a vehicle type.'

        # If not logged in, create an account first
        if not request.user.is_authenticated:
            first_name = request.POST.get('first_name', '').strip()
            last_name  = request.POST.get('last_name', '').strip()
            phone      = request.POST.get('phone', '').strip()
            password   = request.POST.get('password', '')

            if not first_name: errors['first_name'] = 'First name is required.'
            if not phone:      errors['phone']      = 'Phone number is required.'
            if not password or len(password) < 6:
                errors['password'] = 'Password must be at least 6 characters.'
            if phone and User.objects.filter(phone=phone).exists():
                errors['phone'] = 'An account with this number already exists. Sign in first.'

            if errors:
                return render(request, 'rider/apply.html', {
                    'errors': errors, 'form_data': request.POST,
                })

            from django.contrib.auth import login as auth_login
            user = User.objects.create_user(
                phone      = phone,
                username   = phone,
                password   = password,
                first_name = first_name,
                last_name  = last_name,
                role       = 'rider',
            )
            auth_login(request, user)
        else:
            # Update existing user's role to rider
            user = request.user
            user.role = 'rider'
            user.save()

        if errors:
            return render(request, 'rider/apply.html', {
                'errors': errors, 'form_data': request.POST,
            })

        # Create or update the rider profile
        profile, _ = RiderProfile.objects.get_or_create(rider=user)
        profile.vehicle_type  = vehicle_type
        profile.vehicle_plate = vehicle_plate
        profile.status        = RiderProfile.Status.OFFLINE
        if 'id_card' in request.FILES:
            profile.id_card = request.FILES['id_card']
        profile.save()

        messages.success(request, "Application submitted! We'll review your details and notify you shortly.")
        return redirect('rider:pending')

    return render(request, 'rider/apply.html', {})


# ─────────────────────────────
# PENDING APPROVAL PAGE
# ─────────────────────────────
@login_required
def pending(request):
    """
    Shown while the rider's application is being reviewed (is_verified=False).
    If already verified, redirect to dashboard.
    """
    if request.user.role != 'rider':
        return redirect('frontend:home')
    try:
        profile = request.user.rider_profile
        if profile.is_verified:
            return redirect('rider:dashboard')
    except RiderProfile.DoesNotExist:
        return redirect('rider:apply')

    return render(request, 'rider/pending.html', {'profile': profile})


# ─────────────────────────────
# DASHBOARD
# ─────────────────────────────
@rider_required
def dashboard(request):
    profile = request.rider_profile

    active_deliveries = (
        Delivery.objects
        .filter(rider=profile)
        .exclude(status__in=['delivered', 'failed'])
        .select_related('order', 'zone')
        .prefetch_related('order__items')
        .order_by('-assigned_at')
    )

    pending_requests = (
        DeliveryAcceptance.objects
        .filter(rider=profile, status=DeliveryAcceptance.Status.PENDING)
        .select_related('delivery__order', 'delivery__zone')
        .order_by('-created_at')
    )

    recent_earnings = (
        RiderEarning.objects
        .filter(rider=profile)
        .select_related('delivery__order', 'delivery__zone')
        .order_by('-created_at')[:10]
    )

    total_deliveries = Delivery.objects.filter(
        rider=profile, status='delivered'
    ).count()

    total_earnings = (
        RiderEarning.objects.filter(rider=profile)
        .aggregate(t=Sum('amount'))['t'] or 0
    )

    pending_payout = (
        RiderEarning.objects.filter(rider=profile, status='pending')
        .aggregate(t=Sum('amount'))['t'] or 0
    )

    notifications = (
        RiderNotification.objects
        .filter(rider=request.user)
        .order_by('-created_at')[:15]
    )

    unread_count = RiderNotification.objects.filter(
        rider=request.user, is_read=False
    ).count()

    return render(request, 'rider/dashboard.html', {
        'profile':           profile,
        'active_deliveries': active_deliveries,
        'pending_requests':  pending_requests,
        'recent_earnings':   recent_earnings,
        'total_deliveries':  total_deliveries,
        'total_earnings':    total_earnings,
        'pending_payout':    pending_payout,
        'notifications':     notifications,
        'unread_count':      unread_count,
        'cart_count':        0,
    })


# ─────────────────────────────
# ACCEPT DELIVERY
# ─────────────────────────────
@rider_required
def accept_delivery(request, pk):
    if request.method != 'POST':
        return redirect('rider:dashboard')

    profile    = request.rider_profile
    acceptance = get_object_or_404(
        DeliveryAcceptance,
        pk=pk,
        rider=profile,
        status=DeliveryAcceptance.Status.PENDING,
    )
    delivery = acceptance.delivery

    acceptance.status      = DeliveryAcceptance.Status.ACCEPTED
    acceptance.responded_at = timezone.now()
    acceptance.save()

    delivery.status = 'assigned'
    delivery.save()

    profile.status = 'on_delivery'
    profile.save()

    RiderNotification.objects.filter(
        rider=request.user, is_read=False, notif_type='new_delivery'
    ).update(is_read=True)

    messages.success(request, 'Delivery accepted! Check your map.')
    return redirect('rider:live_map', pk=delivery.pk)


# ─────────────────────────────
# REJECT DELIVERY
# ─────────────────────────────
@rider_required
def reject_delivery(request, pk):
    if request.method != 'POST':
        return redirect('rider:dashboard')

    profile    = request.rider_profile
    acceptance = get_object_or_404(
        DeliveryAcceptance,
        pk=pk,
        rider=profile,
        status=DeliveryAcceptance.Status.PENDING,
    )
    acceptance.status       = DeliveryAcceptance.Status.REJECTED
    acceptance.responded_at = timezone.now()
    acceptance.save()

    messages.info(request, 'Delivery rejected.')
    return redirect('rider:dashboard')


# ─────────────────────────────
# LIVE MAP
# ─────────────────────────────
@rider_required
def live_map(request, pk):
    profile  = request.rider_profile
    delivery = get_object_or_404(
        Delivery.objects.select_related('order', 'zone'),
        pk=pk,
        rider=profile,
    )

    # Geocode the customer delivery address
    customer_lat = 5.6037   # Accra fallback
    customer_lng = -0.1870
    try:
        address = (
            f"{delivery.order.delivery_address}, "
            f"{delivery.order.delivery_city}, Ghana"
        )
        url = (
            "https://nominatim.openstreetmap.org/search"
            f"?q={urllib.parse.quote(address)}&format=json&limit=1"
        )
        req = urllib.request.Request(url, headers={'User-Agent': 'Lynctel/1.0'})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
            if data:
                customer_lat = float(data[0]['lat'])
                customer_lng = float(data[0]['lon'])
    except Exception:
        pass

    return render(request, 'rider/live_map.html', {
        'delivery':     delivery,
        'profile':      profile,
        'customer_lat': customer_lat,
        'customer_lng': customer_lng,
        'cart_count':   0,
    })


# ─────────────────────────────
# GPS: UPDATE LOCATION
# ─────────────────────────────
@csrf_exempt
@rider_required
def update_location(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)
    try:
        data = json.loads(request.body)
        lat  = float(data.get('latitude'))
        lng  = float(data.get('longitude'))
    except Exception:
        return JsonResponse({'error': 'Invalid coordinates'}, status=400)

    RiderLocation.objects.update_or_create(
        rider=request.user,
        defaults={'latitude': lat, 'longitude': lng, 'is_active': True},
    )
    return JsonResponse({'success': True})


# ─────────────────────────────
# CUSTOMER TRACKING API
# ─────────────────────────────
def rider_location_api(request, order_ref):
    """
    Called by the customer's tracking page to get the rider's live position.
    URL: /rider/location/<order_ref>/
    """
    try:
        delivery = Delivery.objects.select_related('rider__rider').get(
            order__order_ref=order_ref
        )
        loc = RiderLocation.objects.get(
            rider=delivery.rider.rider, is_active=True
        )
        return JsonResponse({
            'success': True,
            'lat':     float(loc.latitude),
            'lng':     float(loc.longitude),
            'updated': loc.updated_at.strftime('%H:%M:%S'),
            'status':  delivery.status,
            'rider':   delivery.rider.rider.get_full_name(),
            'phone':   delivery.rider.rider.phone,
        })
    except (Delivery.DoesNotExist, RiderLocation.DoesNotExist):
        return JsonResponse({'success': False})


# ─────────────────────────────
# DELIVERY STATUS UPDATE
# ─────────────────────────────
@rider_required
def update_delivery(request, pk):
    if request.method != 'POST':
        return redirect('rider:dashboard')

    profile  = request.rider_profile
    delivery = get_object_or_404(Delivery, pk=pk, rider=profile)

    new_status = request.POST.get('status')
    valid_transitions = {
        'assigned':  ['picked_up', 'failed'],
        'picked_up': ['en_route', 'failed'],
        'en_route':  ['delivered', 'failed'],
    }

    if new_status not in valid_transitions.get(delivery.status, []):
        messages.error(request, 'Invalid status transition.')
        return redirect('rider:dashboard')

    delivery.status = new_status

    if new_status == 'picked_up':
        delivery.picked_up_at = timezone.now()

    elif new_status == 'delivered':
        delivery.delivered_at      = timezone.now()
        delivery.order.status      = 'delivered'
        delivery.order.delivered_at = timezone.now()
        delivery.order.save()

        RiderEarning.objects.get_or_create(
            rider=profile,
            delivery=delivery,
            defaults={'amount': delivery.rider_commission, 'status': 'pending'},
        )

        profile.status = 'available'
        profile.save()

        RiderLocation.objects.filter(rider=request.user).update(is_active=False)

        delivery.save()
        messages.success(
            request,
            f'Delivered! GHS {delivery.rider_commission} earned.',
        )
        return redirect('rider:dashboard')

    elif new_status == 'failed':
        profile.status = 'available'
        profile.save()
        RiderLocation.objects.filter(rider=request.user).update(is_active=False)
        delivery.save()
        messages.warning(request, 'Delivery marked as failed.')
        return redirect('rider:dashboard')

    delivery.save()
    return redirect('rider:live_map', pk=delivery.pk)


# ─────────────────────────────
# TOGGLE ONLINE / OFFLINE
# ─────────────────────────────
@rider_required
def toggle_status(request):
    if request.method != 'POST':
        return redirect('rider:dashboard')

    profile = request.rider_profile

    if profile.status == 'on_delivery':
        messages.warning(request, 'Finish your current delivery first.')
        return redirect('rider:dashboard')

    if profile.status == 'available':
        profile.status = 'offline'
        RiderLocation.objects.filter(rider=request.user).update(is_active=False)
        messages.info(request, 'You are now offline.')
    else:
        profile.status = 'available'
        messages.success(request, 'You are now online and ready for deliveries!')

    profile.save()
    return redirect('rider:dashboard')


# ─────────────────────────────
# NOTIFICATIONS
# ─────────────────────────────
@rider_required
def notification_read(request, pk):
    notif = get_object_or_404(RiderNotification, pk=pk, rider=request.user)
    notif.is_read = True
    notif.save()
    unread = RiderNotification.objects.filter(
        rider=request.user, is_read=False
    ).count()
    return JsonResponse({'success': True, 'unread_count': unread})


@rider_required
def notification_read_all(request):
    RiderNotification.objects.filter(
        rider=request.user, is_read=False
    ).update(is_read=True)
    return JsonResponse({'success': True, 'unread_count': 0})


@rider_required
def notification_count(request):
    unread = RiderNotification.objects.filter(
        rider=request.user, is_read=False
    ).count()
    has_new = RiderNotification.objects.filter(
        rider=request.user, is_read=False, notif_type='new_delivery'
    ).exists()
    return JsonResponse({'count': unread, 'has_new_delivery': has_new})


# ─────────────────────────────
# HELPER — notify a rider
# ─────────────────────────────
def notify_rider(rider_user, title, message, notif_type='new_delivery', link=''):
    RiderNotification.objects.create(
        rider=rider_user,
        title=title,
        message=message,
        notif_type=notif_type,
        link=link,
        is_read=False,
    )


# ─────────────────────────────
# ETA API
# ─────────────────────────────
def eta_api(request):
    try:
        lat  = request.GET.get('lat')
        lng  = request.GET.get('lng')
        dlat = request.GET.get('dest_lat')
        dlng = request.GET.get('dest_lng')

        if not all([lat, lng, dlat, dlng]):
            return JsonResponse({'success': False, 'error': 'Missing coordinates'})

        eta = get_google_eta(float(lat), float(lng), float(dlat), float(dlng))
        if eta is None:
            eta = 10  # safe fallback

        return JsonResponse({'success': True, 'eta': eta})

    except ValueError:
        return JsonResponse({'success': False, 'error': 'Invalid coordinate format'})
    except Exception:
        return JsonResponse({'success': False, 'error': 'Server error'})



 
@login_required
def rider_earnings(request):
    try:
        profile = request.user.rider_profile
    except Exception:
        return redirect('rider:apply')
 
    deliveries = profile.deliveries.select_related(
        'order', 'order__customer'
    ).order_by('-assigned_at')
 
    # ── Stats ──────────────────────────────────────────────────────────────────
    total_earnings = deliveries.filter(
        status='delivered'
    ).aggregate(t=Sum('rider_commission'))['t'] or 0
 
    total_deliveries = deliveries.filter(status='delivered').count()
 
    # This week
    week_start = timezone.now() - timedelta(days=7)
    week_earnings = deliveries.filter(
        status='delivered',
        delivered_at__gte=week_start,
    ).aggregate(t=Sum('rider_commission'))['t'] or 0
 
    week_deliveries = deliveries.filter(
        status='delivered',
        delivered_at__gte=week_start,
    ).count()
 
    # This month
    month_start = timezone.now().replace(day=1, hour=0, minute=0, second=0)
    month_earnings = deliveries.filter(
        status='delivered',
        delivered_at__gte=month_start,
    ).aggregate(t=Sum('rider_commission'))['t'] or 0
 
    # Pending payout (delivered but not yet paid out)
    pending_payout = profile.earnings.filter(
        status='pending'
    ).aggregate(t=Sum('amount'))['t'] or 0
 
    paid_out = profile.earnings.filter(
        status='paid'
    ).aggregate(t=Sum('amount'))['t'] or 0
 
    # Recent completed deliveries
    recent = deliveries.filter(status='delivered')[:20]
 
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
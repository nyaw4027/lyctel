from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from django.db.models import Sum

from delivery.models import Delivery, DeliveryZone
from rider.models import RiderProfile, RiderEarning


# ── Access guard ──────────────────────────────────────────
def rider_required(view_func):
    @login_required
    def wrapper(request, *args, **kwargs):
        if not request.user.is_rider():
            messages.error(request, 'Access denied. Riders only.')
            return redirect('frontend:home')
        try:
            request.rider_profile = request.user.rider_profile
        except RiderProfile.DoesNotExist:
            messages.error(request, 'Rider profile not found. Contact admin.')
            return redirect('frontend:home')
        return view_func(request, *args, **kwargs)
    return wrapper


# ── DASHBOARD ─────────────────────────────────────────────

@rider_required
def dashboard(request):
    profile = request.rider_profile

    active_deliveries = Delivery.objects.filter(
        rider=profile
    ).exclude(
        status__in=['delivered', 'failed']
    ).select_related('order', 'zone').order_by('-assigned_at')

    recent_earnings = RiderEarning.objects.filter(
        rider=profile
    ).select_related('delivery__order').order_by('-created_at')[:10]

    total_deliveries = Delivery.objects.filter(
        rider=profile, status='delivered'
    ).count()

    total_earnings = RiderEarning.objects.filter(
        rider=profile
    ).aggregate(t=Sum('amount'))['t'] or 0

    pending_payout = RiderEarning.objects.filter(
        rider=profile, status='pending'
    ).aggregate(t=Sum('amount'))['t'] or 0

    context = {
        'profile':           profile,
        'active_deliveries': active_deliveries,
        'recent_earnings':   recent_earnings,
        'total_deliveries':  total_deliveries,
        'total_earnings':    total_earnings,
        'pending_payout':    pending_payout,
        'cart_count':        0,
    }
    return render(request, 'rider/dashboard.html', context)


# ── UPDATE DELIVERY STATUS ────────────────────────────────

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

    allowed = valid_transitions.get(delivery.status, [])

    if new_status not in allowed:
        messages.error(request, f'Cannot move from {delivery.status} to {new_status}.')
        return redirect('rider:dashboard')

    # Apply status
    delivery.status = new_status

    if new_status == 'picked_up':
        delivery.picked_up_at = timezone.now()

    elif new_status == 'delivered':
        delivery.delivered_at = timezone.now()
        # Mark order as delivered
        delivery.order.status       = 'delivered'
        delivery.order.delivered_at = timezone.now()
        delivery.order.save()
        # Create earning record
        RiderEarning.objects.get_or_create(
            rider    = profile,
            delivery = delivery,
            defaults = {'amount': delivery.rider_commission, 'status': 'pending'},
        )
        # Free up rider
        profile.status = 'available'
        profile.save()
        messages.success(request, f'Delivery for {delivery.order.order_ref} marked as delivered! GHS {delivery.rider_commission} earned.')

    elif new_status == 'failed':
        profile.status = 'available'
        profile.save()
        messages.warning(request, f'Delivery marked as failed. Admin has been notified.')

    delivery.save()
    return redirect('rider:dashboard')


# ── TOGGLE AVAILABILITY ───────────────────────────────────

@rider_required
def toggle_status(request):
    if request.method != 'POST':
        return redirect('rider:dashboard')

    profile = request.rider_profile

    # Can't go offline mid-delivery
    if profile.status == 'on_delivery':
        messages.warning(request, 'You cannot go offline while on a delivery.')
        return redirect('rider:dashboard')

    if profile.status == 'available':
        profile.status = 'offline'
        messages.info(request, 'You are now offline.')
    else:
        profile.status = 'available'
        messages.success(request, 'You are now available for deliveries!')

    profile.save()
    return redirect('rider:dashboard')


# ── DELIVERY DETAIL ───────────────────────────────────────

@rider_required
def delivery_detail(request, pk):
    profile  = request.rider_profile
    delivery = get_object_or_404(
        Delivery.objects.select_related('order', 'zone'),
        pk=pk, rider=profile
    )
    return render(request, 'rider/delivery_detail.html', {
        'delivery':   delivery,
        'profile':    profile,
        'cart_count': 0,
    })
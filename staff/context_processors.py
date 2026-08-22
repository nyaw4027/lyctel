# staff/context_processors.py
# Add this to TEMPLATES[0]['OPTIONS']['context_processors'] in settings.py:
#   'staff.context_processors.staff_alerts'

def staff_alerts(request):
    """
    Injects staff sidebar badge counts into every template.
    Only runs for authenticated staff/admin users.
    """
    if not request.user.is_authenticated:
        return {}
    if not hasattr(request.user, 'role') or request.user.role not in ('admin', 'staff'):
        return {}

    # Guard: only run on staff paths to avoid overhead on customer pages
    if not request.path.startswith('/staff/') and not request.path.startswith('/rider/admin'):
        return {}

    try:
        from django.db.models import Sum
        from order.models import Order
        from vendors.models import Vendor
        from rider.models import RiderProfile

        ctx = {
            'pending_orders':   Order.objects.filter(status='pending').count(),
            'pending_vendors':  Vendor.objects.filter(status='pending').count(),
            'pending_riders':   RiderProfile.objects.filter(is_verified=False).count(),
        }

        try:
            from rider.models import RiderBalanceSummary
            ctx['rider_balance_count'] = RiderBalanceSummary.objects.filter(
                outstanding__gt=0).count()
        except Exception:
            ctx['rider_balance_count'] = 0

        try:
            from order.models import OrderDispute
            ctx['open_disputes'] = OrderDispute.objects.filter(
                status__in=['open', 'reviewing']).count()
        except Exception:
            ctx['open_disputes'] = 0

        return ctx
    except Exception:
        return {}
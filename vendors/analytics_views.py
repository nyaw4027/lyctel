# ── Vendor Analytics ────────────────────────────────────────────────────────────

from django.contrib.auth.decorators import login_required


@login_required
def vendor_analytics(request):
    """
    Sales analytics dashboard for vendors.
    Shows: revenue trend (30 days), top products, peak order hours,
    payment method breakdown, and commission summary.
    """
    from django.contrib import messages
    from django.shortcuts import render, redirect
    from django.utils import timezone
    from datetime import timedelta
    from django.db.models import Sum, Count, Avg
    from django.db.models.functions import TruncDate, TruncHour
    from order.models import Order, OrderItem
    from django.core.cache import cache

    try:
        vendor = request.user.vendor
    except Exception:
        messages.error(request, 'Vendor account not found.')
        return redirect('vendors:dashboard')

    cache_key = f'vendor_analytics_{vendor.pk}'
    data = cache.get(cache_key)

    if not data:
        now    = timezone.now()
        thirty = now - timedelta(days=30)
        seven  = now - timedelta(days=7)

        # Base querysets
        paid_items = OrderItem.objects.filter(
            product__vendor=vendor,
            order__payment_status='paid',
        ).select_related('order', 'product')

        # Revenue last 30 days by day
        daily = (
            paid_items
            .filter(order__created_at__gte=thirty)
            .annotate(day=TruncDate('order__created_at'))
            .values('day')
            .annotate(revenue=Sum('subtotal'), orders=Count('order', distinct=True))
            .order_by('day')
        )

        # Top 5 products by revenue
        top_products = (
            paid_items
            .filter(order__created_at__gte=thirty)
            .values('product__name', 'product__pk')
            .annotate(revenue=Sum('subtotal'), qty=Sum('quantity'))
            .order_by('-revenue')[:5]
        )

        # Peak hours (0-23) — when orders come in most
        peak_hours = (
            paid_items
            .filter(order__created_at__gte=seven)
            .annotate(hour=TruncHour('order__created_at'))
            .values('hour')
            .annotate(count=Count('order', distinct=True))
            .order_by('hour')
        )

        # Total stats
        total_revenue = paid_items.aggregate(t=Sum('subtotal'))['t'] or 0
        total_orders  = paid_items.values('order').distinct().count()
        avg_order_val = (
            paid_items
            .filter(order__created_at__gte=thirty)
            .values('order')
            .annotate(ov=Sum('subtotal'))
            .aggregate(avg=Avg('ov'))['avg'] or 0
        )

        # Commission paid to Lynctel
        from vendors.models import VendorEarning, AppCommission
        commission_paid = (
            AppCommission.objects
            .filter(vendor=vendor)
            .aggregate(t=Sum('amount'))['t'] or 0
        )

        data = {
            'daily':           list(daily),
            'top_products':    list(top_products),
            'peak_hours':      list(peak_hours),
            'total_revenue':   float(total_revenue),
            'total_orders':    total_orders,
            'avg_order_value': float(avg_order_val),
            'commission_paid': float(commission_paid),
            'net_revenue':     float(total_revenue) - float(commission_paid),
        }
        cache.set(cache_key, data, 300)   # cache 5 mins

    return render(request, 'vendors/analytics.html', {
        'vendor': vendor,
        'data':   data,
        'cart_count': 0,
    })
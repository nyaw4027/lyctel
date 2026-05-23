# staff/views.py
# Complete staff management system for Lynctel
# Staff can manage orders, products, vendors, riders but NOT financials or user roles

from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Sum, Count, Q
from django.utils import timezone
from datetime import timedelta
from functools import wraps

from ecommerce.models import User
from products.models import Product, Category
from order.models import Order, OrderStatusHistory
from delivery.models import Delivery, DeliveryZone
from rider.models import RiderProfile
from vendors.models import Vendor


# ── GUARD ─────────────────────────────────────────────────

def staff_required(view_func):
    """Allow admin and staff roles only."""
    @login_required
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.role in ('admin', 'staff'):
            messages.error(request, 'Access denied. Staff accounts only.')
            return redirect('frontend:home')
        return view_func(request, *args, **kwargs)
    return wrapper


# ── DASHBOARD HOME ────────────────────────────────────────

@staff_required
def dashboard(request):
    today     = timezone.now().date()
    this_week = timezone.now() - timedelta(days=7)

    # Key stats
    total_orders    = Order.objects.count()
    orders_today    = Order.objects.filter(created_at__date=today).count()
    pending_orders  = Order.objects.filter(status='pending').count()
    dispatched      = Order.objects.filter(status='dispatched').count()
    delivered_today = Order.objects.filter(
        status='delivered', delivered_at__date=today
    ).count()

    total_products  = Product.objects.filter(status='active').count()
    low_stock       = Product.objects.filter(status='active', stock_qty__lte=5).count()
    total_vendors   = Vendor.objects.filter(status='active').count()
    pending_vendors = Vendor.objects.filter(status='pending').count()
    total_riders    = RiderProfile.objects.count()
    online_riders   = RiderProfile.objects.filter(status='available').count()

    recent_orders = Order.objects.select_related('customer').order_by('-created_at')[:10]

    pending_vendor_list = Vendor.objects.filter(
        status='pending'
    ).select_related('owner').order_by('-joined_at')[:5]

    low_stock_products = Product.objects.filter(
        status='active', stock_qty__lte=5
    ).select_related('vendor').order_by('stock_qty')[:6]

    return render(request, 'staff/dashboard.html', {
        'total_orders':        total_orders,
        'orders_today':        orders_today,
        'pending_orders':      pending_orders,
        'dispatched':          dispatched,
        'delivered_today':     delivered_today,
        'total_products':      total_products,
        'low_stock':           low_stock,
        'total_vendors':       total_vendors,
        'pending_vendors':     pending_vendors,
        'total_riders':        total_riders,
        'online_riders':       online_riders,
        'recent_orders':       recent_orders,
        'pending_vendor_list': pending_vendor_list,
        'low_stock_products':  low_stock_products,
        'cart_count':          0,
    })


# ── ORDERS ────────────────────────────────────────────────

@staff_required
def order_list(request):
    status = request.GET.get('status', '')
    query  = request.GET.get('q', '').strip()
    orders = Order.objects.select_related('customer').order_by('-created_at')

    if status:
        orders = orders.filter(status=status)
    if query:
        orders = orders.filter(
            Q(order_ref__icontains=query) |
            Q(customer__phone__icontains=query) |
            Q(delivery_city__icontains=query)
        )

    # Status counts for filter bar
    status_counts = {
        'pending':    Order.objects.filter(status='pending').count(),
        'confirmed':  Order.objects.filter(status='confirmed').count(),
        'dispatched': Order.objects.filter(status='dispatched').count(),
        'delivered':  Order.objects.filter(status='delivered').count(),
        'cancelled':  Order.objects.filter(status='cancelled').count(),
    }

    return render(request, 'staff/orders/list.html', {
        'orders':        orders,
        'filter_status': status,
        'query':         query,
        'status_counts': status_counts,
        'cart_count':    0,
    })


@staff_required
def order_detail(request, pk):
    order   = get_object_or_404(Order, pk=pk)
    riders  = RiderProfile.objects.filter(
        is_verified=True, status='available'
    ).select_related('rider')
    zones   = DeliveryZone.objects.filter(is_active=True)
    history = order.status_history.select_related('changed_by').all()

    try:
        delivery = order.delivery
    except Exception:
        delivery = None

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'update_status':
            new_status = request.POST.get('status')
            old_status = order.status
            if new_status and new_status != old_status:
                OrderStatusHistory.objects.create(
                    order=order, old_status=old_status,
                    new_status=new_status, changed_by=request.user,
                    note=request.POST.get('note', ''),
                )
                order.status = new_status
                if new_status == 'delivered':
                    order.delivered_at = timezone.now()
                order.save()
                messages.success(request, f'Order status updated to {new_status}.')

        elif action == 'assign_rider':
            rider_id = request.POST.get('rider_id')
            zone_id  = request.POST.get('zone_id')
            if rider_id and zone_id and not delivery:
                rider = get_object_or_404(RiderProfile, pk=rider_id)
                zone  = get_object_or_404(DeliveryZone, pk=zone_id)

                new_delivery = Delivery.objects.create(
                    order=order, rider=rider, zone=zone,
                    delivery_fee=zone.delivery_fee,
                    rider_commission=zone.delivery_fee * (rider.commission_rate / 100),
                    status='pending_acceptance',
                )

                # Create acceptance record
                try:
                    from rider.location_models import DeliveryAcceptance
                    DeliveryAcceptance.objects.create(
                        delivery=new_delivery, rider=rider, status='pending'
                    )
                except Exception:
                    pass

                order.status = 'confirmed'
                order.save()

                # Notify rider
                try:
                    from rider.views import notify_rider
                    notify_rider(
                        rider_user=rider.rider,
                        title='🛵 New Delivery Request!',
                        message=(
                            f'Order {order.order_ref} — deliver to '
                            f'{order.delivery_address}, {order.delivery_city}. '
                            f'Commission: GHS {new_delivery.rider_commission}.'
                        ),
                        notif_type='new_delivery',
                        link='/rider/',
                    )
                except Exception:
                    pass

                messages.success(request, f'Rider {rider.rider.get_full_name()} notified.')
            elif delivery:
                messages.warning(request, 'A rider is already assigned.')

        return redirect('staff:order_detail', pk=pk)

    return render(request, 'staff/orders/detail.html', {
        'order':    order,
        'riders':   riders,
        'zones':    zones,
        'history':  history,
        'delivery': delivery,
        'cart_count': 0,
    })


# ── PRODUCTS ──────────────────────────────────────────────

@staff_required
def product_list(request):
    query    = request.GET.get('q', '').strip()
    category = request.GET.get('category', '')
    status   = request.GET.get('status', '')

    products = Product.objects.select_related(
        'category', 'vendor'
    ).prefetch_related('images').order_by('-created_at')

    if query:
        products = products.filter(
            Q(name__icontains=query) | Q(vendor__shop_name__icontains=query)
        )
    if category:
        products = products.filter(category__slug=category)
    if status:
        products = products.filter(status=status)

    categories = Category.objects.all()

    return render(request, 'staff/products/list.html', {
        'products':      products,
        'categories':    categories,
        'query':         query,
        'filter_cat':    category,
        'filter_status': status,
        'cart_count':    0,
    })


@staff_required
def product_toggle(request, pk):
    """Quick toggle product active/inactive."""
    product = get_object_or_404(Product, pk=pk)
    if request.method == 'POST':
        product.status = 'inactive' if product.status == 'active' else 'active'
        product.save()
        messages.success(request, f'"{product.name}" set to {product.status}.')
    return redirect('staff:product_list')


# ── VENDORS ───────────────────────────────────────────────

@staff_required
def vendor_list(request):
    status = request.GET.get('status', '')
    query  = request.GET.get('q', '').strip()

    vendors = Vendor.objects.select_related('owner').annotate(
        product_count=Count('products'),
    ).order_by('-joined_at')

    if status:
        vendors = vendors.filter(status=status)
    if query:
        vendors = vendors.filter(
            Q(shop_name__icontains=query) |
            Q(owner__phone__icontains=query) |
            Q(location__icontains=query)
        )

    counts = {
        'pending':   Vendor.objects.filter(status='pending').count(),
        'active':    Vendor.objects.filter(status='active').count(),
        'suspended': Vendor.objects.filter(status='suspended').count(),
    }

    return render(request, 'staff/vendors/list.html', {
        'vendors':       vendors,
        'filter_status': status,
        'query':         query,
        'counts':        counts,
        'cart_count':    0,
    })


@staff_required
def vendor_detail(request, pk):
    vendor   = get_object_or_404(Vendor, pk=pk)
    products = vendor.products.prefetch_related('images').order_by('-created_at')[:20]
    recent_orders = Order.objects.filter(
        items__product__vendor=vendor
    ).distinct().order_by('-created_at')[:10]

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'approve':
            vendor.status      = 'active'
            vendor.approved_at = timezone.now()
            vendor.save()
            messages.success(request, f'"{vendor.shop_name}" approved and is now live!')

        elif action == 'suspend':
            vendor.status = 'suspended'
            vendor.save()
            messages.warning(request, f'"{vendor.shop_name}" has been suspended.')

        elif action == 'reactivate':
            vendor.status = 'active'
            vendor.save()
            messages.success(request, f'"{vendor.shop_name}" reactivated.')

        return redirect('staff:vendor_detail', pk=pk)

    return render(request, 'staff/vendors/detail.html', {
        'vendor':        vendor,
        'products':      products,
        'recent_orders': recent_orders,
        'cart_count':    0,
    })


# ── RIDERS ────────────────────────────────────────────────

@staff_required
def rider_list(request):
    riders = RiderProfile.objects.select_related(
        'rider', 'zone'
    ).annotate(
        total_deliveries=Count('deliveries'),
    ).order_by('-joined_at')

    status = request.GET.get('status', '')
    query  = request.GET.get('q', '').strip()

    if status:
        riders = riders.filter(status=status)
    if query:
        riders = riders.filter(
            Q(rider__first_name__icontains=query) |
            Q(rider__phone__icontains=query)
        )

    return render(request, 'staff/riders/list.html', {
        'riders':        riders,
        'filter_status': status,
        'query':         query,
        'cart_count':    0,
    })


@staff_required
def rider_detail(request, pk):
    profile    = get_object_or_404(RiderProfile, pk=pk)
    deliveries = Delivery.objects.filter(
        rider=profile
    ).select_related('order', 'zone').order_by('-assigned_at')[:20]

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'verify':
            profile.is_verified = not profile.is_verified
            profile.save()
            state = 'verified' if profile.is_verified else 'unverified'
            messages.success(request, f'Rider {state}.')

        elif action == 'update_zone':
            zone_id = request.POST.get('zone_id')
            profile.zone_id = zone_id or None
            profile.save()
            messages.success(request, 'Zone updated.')

        return redirect('staff:rider_detail', pk=pk)

    zones = DeliveryZone.objects.filter(is_active=True)
    return render(request, 'staff/riders/detail.html', {
        'profile':    profile,
        'deliveries': deliveries,
        'zones':      zones,
        'cart_count': 0,
    })


# ── CUSTOMERS ─────────────────────────────────────────────

@staff_required
def customer_list(request):
    query    = request.GET.get('q', '').strip()
    customers = User.objects.filter(role='customer').annotate(
        order_count=Count('orders')
    ).order_by('-created_at')

    if query:
        customers = customers.filter(
            Q(first_name__icontains=query) |
            Q(last_name__icontains=query) |
            Q(phone__icontains=query)
        )

    return render(request, 'staff/customers/list.html', {
        'customers': customers,
        'query':     query,
        'cart_count': 0,
    })


@staff_required
def customer_detail(request, pk):
    customer = get_object_or_404(User, pk=pk, role='customer')
    orders   = Order.objects.filter(customer=customer).order_by('-created_at')
    total_spent = orders.filter(
        payment_status='paid'
    ).aggregate(t=Sum('total_amount'))['t'] or 0

    return render(request, 'staff/customers/detail.html', {
        'customer':    customer,
        'orders':      orders,
        'total_spent': total_spent,
        'cart_count':  0,
    })
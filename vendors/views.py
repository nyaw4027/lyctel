from datetime import timedelta

from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Sum, Count, Q
from django.db.models.functions import TruncDay
from django.utils import timezone
from django.utils.text import slugify

from products.models import Product, Category, ProductImage
from order.models import Order, OrderItem
from .models import Vendor, VendorEarning
# ... your existing imports and decorators remain unchanged ...
from django.urls import reverse


# ── GUARD DECORATOR ───────────────────────────────────────

def vendor_required(view_func):
    @login_required
    def wrapper(request, *args, **kwargs):
        try:
            vendor = request.user.vendor
            if vendor.status != Vendor.Status.ACTIVE:
                messages.warning(request,
                    'Your vendor account is pending approval. We will notify you once approved.')
                return redirect('vendors:pending')
            request.vendor = vendor
        except Vendor.DoesNotExist:
            messages.info(request, 'Apply to become a vendor first.')
            return redirect('vendors:apply')
        return view_func(request, *args, **kwargs)
    return wrapper


# ── PUBLIC: VENDOR DIRECTORY ──────────────────────────────

def directory(request):
    # Changed annotation alias to 'total_products' to avoid potential property clashes
    vendors = Vendor.objects.filter(
        status=Vendor.Status.ACTIVE
    ).annotate(total_products=Count('products')).order_by('-joined_at')

    search = request.GET.get('q', '').strip()
    if search:
        vendors = vendors.filter(
            Q(shop_name__icontains=search) |
            Q(description__icontains=search) |
            Q(location__icontains=search)
        )

    return render(request, 'vendors/directory.html', {
        'vendors':    vendors,
        'search':     search,
        'cart_count': _get_cart_count(request),
    })


# ── PUBLIC: VENDOR SHOP PAGE ──────────────────────────────

def shop_page(request, slug):
    # Using select_related to optimize fetching profile data
    vendor = get_object_or_404(
    Vendor.objects.select_related('owner'),
    slug=slug,
    status=Vendor.Status.ACTIVE
)

    products = (
        vendor.products
        .filter(status='active')
        .select_related('category')
        .prefetch_related('images')
    )

    search = request.GET.get('q', '').strip()
    filter_cat = request.GET.get('category', '').strip()
    sort = request.GET.get('sort', 'newest')

    if search:
        products = products.filter(
            Q(name__icontains=search) | Q(description__icontains=search)
        )
    if filter_cat:
        products = products.filter(category__slug=filter_cat)

    sort_map = {
        'newest': '-created_at',
        'price_low': 'selling_price',
        'price_high': '-selling_price',
        'name': 'name',
    }
    products = products.order_by(sort_map.get(sort, '-created_at'))

    categories = (
        Category.objects
        .filter(products__vendor=vendor, products__status='active', is_active=True)
        .annotate(total_items=Count('products'))
        .distinct()
    )

    return render(request, 'vendors/shop.html', {
        'vendor': vendor,
        'products': products,
        'categories': categories,
        'total_products': vendor.products.filter(status='active').count(),
        'search': search,
        'filter_cat': filter_cat,
        'sort': sort,
        'cart_count': _get_cart_count(request),
    })


# ── APPLY TO BECOME A VENDOR ──────────────────────────────

def apply(request):
    if request.user.is_authenticated:
        try:
            vendor = request.user.vendor
            if vendor.status == Vendor.Status.ACTIVE:
                return redirect('vendors:dashboard')
            return render(request, 'vendors/pending.html', {'vendor': vendor})
        except Vendor.DoesNotExist:
            pass

    if request.method == 'POST':
        shop_name    = request.POST.get('shop_name', '').strip()
        description  = request.POST.get('description', '').strip()
        phone        = request.POST.get('phone', '').strip()
        location     = request.POST.get('location', '').strip()
        momo_number  = request.POST.get('momo_number', '').strip()
        momo_network = request.POST.get('momo_network', '')
        first_name   = request.POST.get('first_name', '').strip()
        last_name    = request.POST.get('last_name', '').strip()
        password     = request.POST.get('password', '')

        errors = {}
        if not shop_name:   errors['shop_name']   = 'Shop name is required.'
        if not phone:       errors['phone']        = 'Phone number is required.'
        if not momo_number: errors['momo_number']  = 'MoMo number is required for payouts.'

        if not request.user.is_authenticated:
            if not first_name:    errors['first_name'] = 'First name is required.'
            if not password:      errors['password']   = 'Password is required.'
            if len(password) < 6: errors['password']   = 'Password must be at least 6 characters.'
            from ecommerce.models import User
            if User.objects.filter(phone=phone).exists():
                errors['phone'] = 'An account with this number already exists. Sign in first.'

        if errors:
            return render(request, 'vendors/apply.html', {
                'errors': errors, 'form_data': request.POST
            })

        if not request.user.is_authenticated:
            from ecommerce.models import User
            from django.contrib.auth import login as auth_login
            user = User.objects.create_user(
                username=phone, phone=phone, password=password,
                first_name=first_name, last_name=last_name, role='customer',
            )
            auth_login(request, user)
        else:
            user = request.user

        vendor = Vendor.objects.create(
            owner=user, shop_name=shop_name, description=description,
            phone=phone, location=location, momo_number=momo_number,
            momo_network=momo_network, status=Vendor.Status.PENDING,
        )
        if 'logo' in request.FILES:
            vendor.logo = request.FILES['logo']
            vendor.save()

        messages.success(request, f'Application submitted! We\'ll review "{shop_name}" shortly.')
        return redirect('vendors:pending')

    return render(request, 'vendors/apply.html', {})


@login_required
def pending(request):
    try:
        vendor = request.user.vendor
    except Vendor.DoesNotExist:
        return redirect('vendors:apply')
    return render(request, 'vendors/pending.html', {'vendor': vendor})
    
#DASHBOARD VIEWS
@vendor_required
def dashboard(request):
    vendor = request.vendor
    
    # 1. Determine which tab or sub-pane the user wants to look at
    current_tab = request.GET.get('tab', 'products')  # defaults to products list
    pane = request.GET.get('pane', '')               # detects sub-panels like social configuration

    # ═══════════════════════════════════════════════════
    #  SUB-PANE: RENDER & SAVE STANDALONE SOCIALS FORM
    # ═══════════════════════════════════════════════════
    if current_tab == 'settings' and pane == 'social':
        if request.method == 'POST':
            # Extract and update ALL 6 input values matching socials_form.html exactly
            vendor.whatsapp  = request.POST.get('whatsapp', '').strip()
            vendor.instagram = request.POST.get('instagram', '').strip()
            vendor.facebook  = request.POST.get('facebook', '').strip()
            vendor.tiktok    = request.POST.get('tiktok', '').strip()
            vendor.twitter   = request.POST.get('twitter', '').strip()   # Fixed: Was missing
            vendor.youtube   = request.POST.get('youtube', '').strip()   # Fixed: Was missing
            
            vendor.save()
            messages.success(request, "Social configurations updated successfully.")
            # Bounces them clean back onto the core settings panel view context
            return redirect(f"{reverse('vendors:dashboard')}?tab=settings")
            
        # If GET request, render your dedicated standalone form file with clear vendor context
        return render(request, 'vendors/socials_form.html', {
            'vendor': vendor,
            'cart_count': 0,
            'current_tab': current_tab,
            'pane': pane
        })

    # ═══════════════════════════════════════════════════
    #  STANDARD SETTINGS TAB SUBMISSION (Shop Profile)
    # ═══════════════════════════════════════════════════
    if current_tab == 'settings' and request.method == 'POST':
        vendor.shop_name    = request.POST.get('shop_name', vendor.shop_name).strip()
        vendor.description  = request.POST.get('description', '').strip()
        vendor.phone        = request.POST.get('phone', vendor.phone).strip()
        vendor.location     = request.POST.get('location', '').strip()
        vendor.momo_number  = request.POST.get('momo_number', vendor.momo_number).strip()
        vendor.momo_network = request.POST.get('momo_network', vendor.momo_network)

        if 'logo' in request.FILES:
            vendor.logo = request.FILES['logo']
        if 'banner' in request.FILES:
            vendor.banner = request.FILES['banner']

        vendor.save()
        messages.success(request, 'Shop settings saved!')
        return redirect(f"{reverse('vendors:dashboard')}?tab=settings")

    # 3. Base Dashboard Querysets
    products = (
        vendor.products
        .prefetch_related('images')
        .select_related('category')
        .order_by('-created_at')
    )
    earnings = VendorEarning.objects.filter(vendor=vendor).select_related('order')

    # Core statistical aggregates
    total_revenue   = earnings.aggregate(t=Sum('net_amount'))['t'] or 0
    pending_payout  = earnings.filter(status='pending').aggregate(t=Sum('net_amount'))['t'] or 0
    paid_out        = earnings.filter(status='paid').aggregate(t=Sum('net_amount'))['t'] or 0
    total_orders    = earnings.count()
    low_stock_count = products.filter(status='active', stock_qty__lte=5).count()

    # Timezone-Aware range extraction for "Today" analytics
    today_start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = today_start + timedelta(days=1)

    orders_today = OrderItem.objects.filter(
        product__vendor=vendor,
        order__created_at__range=(today_start, today_end),
        order__payment_status='paid',
    ).count()
    
    revenue_today = earnings.filter(
        created_at__range=(today_start, today_end)
    ).aggregate(t=Sum('net_amount'))['t'] or 0

    # Weekly timeline charting data serialization
    seven_days_ago = timezone.now() - timedelta(days=7)
    daily_sales_qs = (
        earnings.filter(created_at__gte=seven_days_ago)
        .annotate(day=TruncDay('created_at'))
        .values('day')
        .annotate(total=Sum('net_amount'))
        .order_by('day')
    )

    daily_sales_list = [
        {
            'day': item['day'].strftime('%Y-%m-%d') if item['day'] else '',
            'total': float(item['total'] or 0)
        }
        for item in daily_sales_qs
    ]

    # Product insights
    top_product = vendor.products.annotate(total_sold=Sum('orderitem__quantity')).order_by('-total_sold').first()
    low_stock_products = vendor.products.filter(status='active', stock_qty__lte=5)[:5]
    recent_orders = (
        OrderItem.objects
        .filter(product__vendor=vendor, order__payment_status='paid')
        .select_related('order', 'product')
        .order_by('-order__created_at')[:20]
    )

    tabs = [
        ('products', 'Products'),
        ('orders',   'Orders'),
        ('earnings', 'Earnings'),
        ('settings', 'Settings'),
    ]

    return render(request, 'vendors/dashboard.html', {
        'vendor':              vendor,
        'products':            products,
        'earnings':            earnings.order_by('-created_at'),
        'recent_orders':       recent_orders,
        'tabs':                tabs,
        'current_tab':         current_tab,

        # Numeric Stats
        'total_revenue':       total_revenue,
        'pending_payout':      pending_payout,
        'paid_out':            paid_out,
        'total_orders':        total_orders,
        'low_stock_count':     low_stock_count,

        # Periodic Metrics
        'orders_today':        orders_today,
        'revenue_today':       revenue_today,
        'daily_sales':         daily_sales_list,

        # Product insights
        'top_product':         top_product,
        'low_stock_products':  low_stock_products,
        'cart_count':          0,
    })
# ── VENDOR PRODUCT MANAGEMENT ─────────────────────────────

@vendor_required
def product_add(request):
    vendor     = request.vendor
    categories = Category.objects.filter(is_active=True)

    if request.method == 'POST':
        name          = request.POST.get('name', '').strip()
        description   = request.POST.get('description', '').strip()
        category_id   = request.POST.get('category_id')
        selling_price = request.POST.get('selling_price')
        stock_qty     = request.POST.get('stock_qty', 0)
        status        = request.POST.get('status', 'active')

        errors = {}
        if not name:          errors['name']          = 'Product name is required.'
        if not selling_price: errors['selling_price'] = 'Selling price is required.'

        if errors:
            return render(request, 'vendors/product_form.html', {
                'vendor': vendor, 'categories': categories,
                'errors': errors, 'form_data': request.POST, 'action': 'Add',
            })

        base_slug = slugify(name)
        slug, n = base_slug, 1
        while Product.objects.filter(slug=slug).exists():
            slug = f"{base_slug}-{n}"; n += 1

        product = Product.objects.create(
            vendor=vendor, name=name, slug=slug, description=description,
            category_id=category_id or None, selling_price=selling_price,
            cost_price=selling_price, stock_qty=stock_qty, status=status,
        )
        for i, img in enumerate(request.FILES.getlist('images')):
            ProductImage.objects.create(
                product=product, image=img, is_primary=(i == 0), order=i
            )

        messages.success(request, f'"{product.name}" added to your shop!')
        return redirect('vendors:dashboard')

    return render(request, 'vendors/product_form.html', {
        'vendor': vendor, 'categories': categories, 'action': 'Add',
    })


@vendor_required
def product_edit(request, pk):
    vendor     = request.vendor
    product    = get_object_or_404(Product, pk=pk, vendor=vendor)
    categories = Category.objects.filter(is_active=True)

    if request.method == 'POST':
        product.name          = request.POST.get('name', product.name).strip()
        product.description   = request.POST.get('description', '').strip()
        product.category_id   = request.POST.get('category_id') or None
        product.selling_price = request.POST.get('selling_price', product.selling_price)
        product.cost_price    = product.selling_price
        product.stock_qty     = request.POST.get('stock_qty', product.stock_qty)
        product.status        = request.POST.get('status', product.status)
        product.save()

        for i, img in enumerate(request.FILES.getlist('images')):
            ProductImage.objects.create(
                product=product, image=img, order=product.images.count() + i
            )

        messages.success(request, f'"{product.name}" updated!')
        return redirect('vendors:dashboard')

    return render(request, 'vendors/product_form.html', {
        'vendor': vendor, 'product': product, 'categories': categories, 'action': 'Edit',
    })


@vendor_required
def product_delete(request, pk):
    vendor  = request.vendor
    product = get_object_or_404(Product, pk=pk, vendor=vendor)
    if request.method == 'POST':
        name = product.name
        product.delete()
        messages.success(request, f'"{name}" deleted.')
    return redirect('vendors:dashboard')


# ── VENDOR EARNINGS ───────────────────────────────────────

@vendor_required
def earnings(request):
    vendor   = request.vendor
    earnings = VendorEarning.objects.filter(
        vendor=vendor
    ).select_related('order').order_by('-created_at')

    total    = earnings.aggregate(t=Sum('net_amount'))['t'] or 0
    pending  = earnings.filter(status='pending').aggregate(t=Sum('net_amount'))['t'] or 0
    paid_out = earnings.filter(status='paid').aggregate(t=Sum('net_amount'))['t'] or 0

    return render(request, 'vendors/earnings.html', {
        'vendor':   vendor,
        'earnings': earnings,
        'total':    total,
        'pending':  pending,
        'paid_out': paid_out,
    })


# ── HELPER ────────────────────────────────────────────────

def _get_cart_count(request):
    if request.user.is_authenticated:
        try:
            return request.user.cart.total_items
        except Exception:
            return 0
    return 0


# ── VENDOR DISPATCH (manual rider assignment) ──────────────

@vendor_required
def dispatch_ride(request):
    from delivery.models import Delivery
    from delivery.views import _push_prompt_to_rider
    from rider.models import RiderProfile, DeliveryAcceptance
    from rider.views import notify_rider

    vendor = request.vendor

    pending_deliveries = (
        Delivery.objects
        .filter(
            order__items__product__vendor=vendor,
            status=Delivery.Status.PENDING,
        )
        .select_related("order", "zone")
        .distinct()
    )

    available_riders = (
        RiderProfile.objects
        .filter(status=RiderProfile.Status.AVAILABLE)
        .select_related("rider", "zone")
    )

    if request.method == "POST":
        delivery_id = request.POST.get("delivery_id")
        rider_id    = request.POST.get("rider_id")

        delivery = get_object_or_404(Delivery, pk=delivery_id)
        rider    = get_object_or_404(RiderProfile, pk=rider_id)

        acceptance, created = DeliveryAcceptance.objects.get_or_create(
            delivery=delivery,
            defaults={"rider": rider, "status": DeliveryAcceptance.Status.PENDING},
        )
        if not created:
            acceptance.rider        = rider
            acceptance.status       = DeliveryAcceptance.Status.PENDING
            acceptance.responded_at = None
            acceptance.save()

        _push_prompt_to_rider(rider, delivery, acceptance)

        notify_rider(
            rider.rider,
            "New Delivery Request",
            f"Vendor dispatch — Pickup: {delivery.pickup_location or delivery.order.delivery_address}",
            notif_type="new_delivery",
            link="/rider/",
        )

        messages.success(
            request,
            f"Request sent to {rider.rider.get_full_name() or rider.rider.phone}. "
            "They'll accept or reject shortly."
        )
        return redirect("vendors:dispatch")

    return render(request, "vendors/dispatch.html", {
        "pending_deliveries": pending_deliveries,
        "available_riders":   available_riders,
    })
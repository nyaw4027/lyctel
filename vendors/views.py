import os
from datetime import timedelta

from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Sum, Count, Q, F
from django.db.models.functions import TruncDay
from django.utils import timezone
from django.utils.text import slugify

from products.models import Product, Category, ProductImage, ProductVideo
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

    # FIXED: previously chained .filter(products__vendor=vendor, products__status='active')
    # then .annotate(Count('products')) on the SAME relation, which caused Django to
    # build a multi-row join and count ALL of the category's products (every vendor),
    # not just this vendor's active ones. Using a conditional Count avoids the
    # double-join and gives the correct per-vendor count.
    categories = (
        Category.objects
        .filter(is_active=True)
        .annotate(
            total_items=Count(
                'products',
                filter=Q(products__vendor=vendor, products__status='active')
            )
        )
        .filter(total_items__gt=0)
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
        if not shop_name:   errors['shop_name']  = 'Shop name is required.'
        if not phone:       errors['phone']       = 'Phone number is required.'
        if not momo_number: errors['momo_number'] = 'MoMo number is required for payouts.'

        if not request.user.is_authenticated:
            from ecommerce.models import User
            if not first_name:
                errors['first_name'] = 'First name is required.'
            if not password:
                errors['password'] = 'Password is required.'
            elif len(password) < 6:
                errors['password'] = 'Password must be at least 6 characters.'
            if phone and User.objects.filter(phone=phone).exists():
                errors['phone'] = 'An account with this number already exists. Sign in first.'

        if errors:
            return render(request, 'vendors/apply.html', {
                'errors': errors, 'form_data': request.POST
            })

        if not request.user.is_authenticated:
            from ecommerce.models import User
            from django.contrib.auth import login as auth_login
            user = User.objects.create_user(
                phone=phone,
                password=password,
                first_name=first_name,
                last_name=last_name,
                role='vendor',
            )
            auth_login(request, user, backend='django.contrib.auth.backends.ModelBackend')
        else:
            user = request.user
            # Update role to vendor if they were a customer
            if user.role == 'customer':
                user.role = 'vendor'
                user.save(update_fields=['role'])

        vendor = Vendor.objects.create(
            owner        = user,
            shop_name    = shop_name,
            description  = description,
            phone        = phone,
            location     = location,
            momo_number  = momo_number,
            momo_network = momo_network,
            logo         = request.FILES.get('logo') or None,
            status       = Vendor.Status.PENDING,
        )

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


# DASHBOARD VIEWS
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

    # FIXED: previously hardcoded stock_qty__lte=5, ignoring each product's own
    # low_stock_alert threshold (the field that already exists on the model and
    # backs Product.is_low_stock). Now uses F() to compare against that field.
    low_stock_count = products.filter(
        status='active', stock_qty__lte=F('low_stock_alert')
    ).count()

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
    # FIXED: previously summed orderitem__quantity across ALL order items regardless
    # of payment status, which could rank an unpaid/cancelled order's product as
    # "top product." Now restricted to paid orders, consistent with orders_today /
    # revenue_today / recent_orders below.
    top_product = vendor.products.annotate(
        total_sold=Sum(
            'orderitem__quantity',
            filter=Q(orderitem__order__payment_status='paid')
        )
    ).order_by('-total_sold').first()

    # FIXED: same low_stock_alert issue as low_stock_count above.
    low_stock_products = vendor.products.filter(
        status='active', stock_qty__lte=F('low_stock_alert')
    )[:5]

    recent_orders = (
        OrderItem.objects
        .filter(product__vendor=vendor, order__payment_status='paid')
        .select_related('order', 'product')
        .order_by('-order__created_at')[:20]
    )

    tabs = [
        ('products', 'Products'),
        ('orders',   'Orders'),
        ('videos',   'Videos'),
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

ALLOWED_VIDEO_EXTENSIONS = ('.mp4', '.mov', '.webm')
MAX_VIDEO_SIZE_BYTES = 50 * 1024 * 1024  # 50MB


def _validate_video_upload(video_file, errors):
    """Shared validation for product video uploads. Mutates `errors` in place."""
    if not video_file:
        return
    ext = os.path.splitext(video_file.name)[1].lower()
    if ext not in ALLOWED_VIDEO_EXTENSIONS:
        errors['video'] = 'Unsupported video format. Use MP4, MOV, or WebM.'
    elif video_file.size > MAX_VIDEO_SIZE_BYTES:
        errors['video'] = 'Video file is too large. Maximum size is 50MB.'


def _validate_discount_price(discount_price, selling_price, errors):
    """Shared validation for the discount/deal price field. Mutates `errors` in place."""
    if not discount_price:
        return
    try:
        if float(discount_price) >= float(selling_price):
            errors['discount_price'] = 'Discount price must be lower than the selling price.'
    except (TypeError, ValueError):
        errors['discount_price'] = 'Enter a valid discount price.'


@vendor_required
def product_add(request):
    vendor     = request.vendor
    categories = Category.objects.filter(is_active=True)

    if request.method == 'POST':
        name           = request.POST.get('name', '').strip()
        description    = request.POST.get('description', '').strip()
        category_id    = request.POST.get('category_id')
        selling_price  = request.POST.get('selling_price')
        discount_price = request.POST.get('discount_price', '').strip()
        stock_qty      = request.POST.get('stock_qty', 0)
        status         = request.POST.get('status', 'active')

        # FIXED: video upload fields were read nowhere in this view, so the
        # ProductVideo row was never created even though the form/template
        # already supported uploading one.
        video_file  = request.FILES.get('video')
        video_title = request.POST.get('video_title', '').strip()
        video_thumb = request.FILES.get('video_thumbnail')

        errors = {}
        if not name:          errors['name']          = 'Product name is required.'
        if not selling_price: errors['selling_price'] = 'Selling price is required.'

        # FIXED: discount_price was accepted by the template but never read/validated
        # here, so deal pricing could never actually be set from this form.
        _validate_discount_price(discount_price, selling_price, errors)
        _validate_video_upload(video_file, errors)

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
            discount_price=discount_price or None,
            cost_price=selling_price, stock_qty=stock_qty, status=status,
        )
        for i, img in enumerate(request.FILES.getlist('images')):
            ProductImage.objects.create(
                product=product, image=img, is_primary=(i == 0), order=i
            )

        if video_file:
            ProductVideo.objects.create(
                product=product,
                video=video_file,
                thumbnail=video_thumb,
                title=video_title,
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
        # FIXED: the dashboard's Videos tab posts only csrf + delete_videos
        # to this exact view (no name/description/category_id/etc). Letting
        # that fall through into the full save logic below silently wiped
        # the product's description (defaulted to '') and unset its
        # category (defaulted to None) as a side effect of removing a video.
        # Handle it as its own action and return immediately.
        delete_video_ids = request.POST.getlist('delete_videos')
        if delete_video_ids and 'name' not in request.POST:
            ProductVideo.objects.filter(product=product, pk__in=delete_video_ids).delete()
            messages.success(request, 'Video removed.')
            return redirect('vendors:dashboard')

        name           = request.POST.get('name', product.name).strip()
        selling_price  = request.POST.get('selling_price', product.selling_price)
        discount_price = request.POST.get('discount_price', '').strip()

        video_file  = request.FILES.get('video')
        video_title = request.POST.get('video_title', '').strip()
        video_thumb = request.FILES.get('video_thumbnail')

        # FIXED: product_edit previously had NO required-field checks at all
        # (product_add does). If name or selling_price ever came through
        # blank, product.save() would raise an unhandled exception instead
        # of re-rendering the form with a friendly error.
        errors = {}
        if not name:          errors['name']          = 'Product name is required.'
        if not selling_price: errors['selling_price'] = 'Selling price is required.'
        _validate_discount_price(discount_price, selling_price, errors)
        _validate_video_upload(video_file, errors)

        if errors:
            return render(request, 'vendors/product_form.html', {
                'vendor': vendor, 'product': product, 'categories': categories,
                'errors': errors, 'form_data': request.POST, 'action': 'Edit',
            })

        product.name           = name
        product.description    = request.POST.get('description', '').strip()
        product.category_id    = request.POST.get('category_id') or None
        product.selling_price  = selling_price
        product.discount_price = discount_price or None
        product.cost_price     = product.selling_price
        product.stock_qty      = request.POST.get('stock_qty', product.stock_qty)
        product.status         = request.POST.get('status', product.status)
        product.save()

        for i, img in enumerate(request.FILES.getlist('images')):
            ProductImage.objects.create(
                product=product, image=img, order=product.images.count() + i
            )

        if video_file:
            ProductVideo.objects.create(
                product=product,
                video=video_file,
                thumbnail=video_thumb,
                title=video_title,
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
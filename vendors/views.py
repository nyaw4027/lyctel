import os
import uuid
from datetime import timedelta
from decimal import Decimal

from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.cache import cache
from django.db.models import Sum, Count, Avg, Q, F
from django.db.models.functions import TruncDay, TruncDate, TruncHour
from django.http import JsonResponse
from django.utils import timezone
from django.utils.text import slugify
from django.urls import reverse

from products.models import Product, Category, ProductImage, ProductVideo
from order.models import Order, OrderItem
from .models import Vendor, VendorEarning


# ── GUARD DECORATOR ─────────────────────────────────────────────────────────

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
    wrapper.__name__ = view_func.__name__
    return wrapper


# ── PUBLIC: VENDOR DIRECTORY ─────────────────────────────────────────────────

def directory(request):
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


# ── PUBLIC: VENDOR SHOP PAGE ─────────────────────────────────────────────────

def shop_page(request, slug):
    vendor = get_object_or_404(
        Vendor.objects.select_related('owner'),
        slug=slug, status=Vendor.Status.ACTIVE,
    )
    products = (
        vendor.products
        .filter(status='active')
        .select_related('category')
        .prefetch_related('images')
    )

    search     = request.GET.get('q', '').strip()
    filter_cat = request.GET.get('category', '').strip()
    sort       = request.GET.get('sort', 'newest')

    if search:
        products = products.filter(
            Q(name__icontains=search) | Q(description__icontains=search)
        )
    if filter_cat:
        products = products.filter(category__slug=filter_cat)

    sort_map = {
        'newest':     '-created_at',
        'price_low':  'selling_price',
        'price_high': '-selling_price',
        'name':       'name',
    }
    products = products.order_by(sort_map.get(sort, '-created_at'))

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
        'vendor':         vendor,
        'products':       products,
        'categories':     categories,
        'total_products': vendor.products.filter(status='active').count(),
        'search':         search,
        'filter_cat':     filter_cat,
        'sort':           sort,
        'cart_count':     _get_cart_count(request),
    })


# ── APPLY TO BECOME A VENDOR ─────────────────────────────────────────────────

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
                phone=phone, password=password,
                first_name=first_name, last_name=last_name, role='vendor',
            )
            auth_login(request, user, backend='django.contrib.auth.backends.ModelBackend')
        else:
            user = request.user
            if user.role == 'customer':
                user.role = 'vendor'
                user.save(update_fields=['role'])

        vendor = Vendor.objects.create(
            owner=user, shop_name=shop_name, description=description,
            phone=phone, location=location, momo_number=momo_number,
            momo_network=momo_network,
            logo=request.FILES.get('logo') or None,
            status=Vendor.Status.PENDING,
        )

        # Credit referrer if signup came via referral link
        _apply_referral_on_signup(user, request)

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


# ── DASHBOARD ────────────────────────────────────────────────────────────────

@vendor_required
def dashboard(request):
    vendor      = request.vendor
    current_tab = request.GET.get('tab', 'products')
    pane        = request.GET.get('pane', '')

    # ── Social settings sub-pane ─────────────────────────────────────────────
    if current_tab == 'settings' and pane == 'social':
        if request.method == 'POST':
            vendor.whatsapp  = request.POST.get('whatsapp', '').strip()
            vendor.instagram = request.POST.get('instagram', '').strip()
            vendor.facebook  = request.POST.get('facebook', '').strip()
            vendor.tiktok    = request.POST.get('tiktok', '').strip()
            vendor.twitter   = request.POST.get('twitter', '').strip()
            vendor.youtube   = request.POST.get('youtube', '').strip()
            vendor.save()
            messages.success(request, 'Social configurations updated successfully.')
            return redirect(f"{reverse('vendors:dashboard')}?tab=settings")
        return render(request, 'vendors/socials_form.html', {
            'vendor': vendor, 'cart_count': 0,
            'current_tab': current_tab, 'pane': pane,
        })

    # ── Standard settings tab ─────────────────────────────────────────────────
    if current_tab == 'settings' and request.method == 'POST':
        vendor.shop_name    = request.POST.get('shop_name',    vendor.shop_name).strip()
        vendor.description  = request.POST.get('description',  '').strip()
        vendor.phone        = request.POST.get('phone',         vendor.phone).strip()
        vendor.location     = request.POST.get('location',      '').strip()
        vendor.momo_number  = request.POST.get('momo_number',   vendor.momo_number).strip()
        vendor.momo_network = request.POST.get('momo_network',  vendor.momo_network)
        if 'logo'   in request.FILES: vendor.logo   = request.FILES['logo']
        if 'banner' in request.FILES: vendor.banner = request.FILES['banner']
        vendor.save()
        messages.success(request, 'Shop settings saved!')
        return redirect(f"{reverse('vendors:dashboard')}?tab=settings")

    # ── Querysets ─────────────────────────────────────────────────────────────
    products = (
        vendor.products
        .prefetch_related('images')
        .select_related('category')
        .order_by('-created_at')
    )
    earnings_qs = VendorEarning.objects.filter(vendor=vendor).select_related('order')

    total_revenue  = earnings_qs.aggregate(t=Sum('net_amount'))['t'] or 0
    pending_payout = earnings_qs.filter(status='pending').aggregate(t=Sum('net_amount'))['t'] or 0
    held_payout    = earnings_qs.filter(status='held').aggregate(t=Sum('net_amount'))['t'] or 0
    paid_out       = earnings_qs.filter(status='paid').aggregate(t=Sum('net_amount'))['t'] or 0
    total_orders   = earnings_qs.count()

    low_stock_count = products.filter(
        status='active', stock_qty__lte=F('low_stock_alert')
    ).count()

    today_start   = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
    today_end     = today_start + timedelta(days=1)
    orders_today  = OrderItem.objects.filter(
        product__vendor=vendor,
        order__created_at__range=(today_start, today_end),
        order__payment_status='paid',
    ).count()
    revenue_today = earnings_qs.filter(
        created_at__range=(today_start, today_end)
    ).aggregate(t=Sum('net_amount'))['t'] or 0

    seven_days_ago  = timezone.now() - timedelta(days=7)
    daily_sales_qs  = (
        earnings_qs.filter(created_at__gte=seven_days_ago)
        .annotate(day=TruncDay('created_at'))
        .values('day')
        .annotate(total=Sum('net_amount'))
        .order_by('day')
    )
    daily_sales_list = [
        {'day': item['day'].strftime('%Y-%m-%d') if item['day'] else '', 'total': float(item['total'] or 0)}
        for item in daily_sales_qs
    ]

    top_product = vendor.products.annotate(
        total_sold=Sum('orderitem__quantity', filter=Q(orderitem__order__payment_status='paid'))
    ).order_by('-total_sold').first()

    low_stock_products = vendor.products.filter(
        status='active', stock_qty__lte=F('low_stock_alert')
    )[:5]

    recent_orders = (
        OrderItem.objects
        .filter(product__vendor=vendor, order__payment_status='paid')
        .select_related('order', 'product')
        .order_by('-order__created_at')[:20]
    )

    return render(request, 'vendors/dashboard.html', {
        'vendor':             vendor,
        'products':           products,
        'earnings':           earnings_qs.order_by('-created_at'),
        'recent_orders':      recent_orders,
        'tabs':               [('products','Products'),('orders','Orders'),
                               ('videos','Videos'),('earnings','Earnings'),('settings','Settings')],
        'current_tab':        current_tab,
        'total_revenue':      total_revenue,
        'pending_payout':     pending_payout,
        'held_payout':        held_payout,
        'paid_out':           paid_out,
        'total_orders':       total_orders,
        'low_stock_count':    low_stock_count,
        'orders_today':       orders_today,
        'revenue_today':      revenue_today,
        'daily_sales':        daily_sales_list,
        'top_product':        top_product,
        'low_stock_products': low_stock_products,
        'cart_count':         0,
    })


# ── PRODUCT MANAGEMENT ───────────────────────────────────────────────────────

ALLOWED_VIDEO_EXTENSIONS = ('.mp4', '.mov', '.webm')
MAX_VIDEO_SIZE_BYTES      = 50 * 1024 * 1024   # 50 MB


def _validate_video_upload(video_file, errors):
    if not video_file:
        return
    ext = os.path.splitext(video_file.name)[1].lower()
    if ext not in ALLOWED_VIDEO_EXTENSIONS:
        errors['video'] = 'Unsupported video format. Use MP4, MOV, or WebM.'
    elif video_file.size > MAX_VIDEO_SIZE_BYTES:
        errors['video'] = 'Video file is too large. Maximum size is 50 MB.'


def _validate_discount_price(discount_price, selling_price, errors):
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
        video_file     = request.FILES.get('video')
        video_title    = request.POST.get('video_title', '').strip()
        video_thumb    = request.FILES.get('video_thumbnail')

        errors = {}
        if not name:          errors['name']          = 'Product name is required.'
        if not selling_price: errors['selling_price'] = 'Selling price is required.'
        _validate_discount_price(discount_price, selling_price, errors)
        _validate_video_upload(video_file, errors)

        if errors:
            return render(request, 'vendors/product_form.html', {
                'vendor': vendor, 'categories': categories,
                'errors': errors, 'form_data': request.POST, 'action': 'Add',
            })

        base_slug = slugify(name)
        slug, n   = base_slug, 1
        while Product.objects.filter(slug=slug).exists():
            slug = f'{base_slug}-{n}'; n += 1

        product = Product.objects.create(
            vendor=vendor, name=name, slug=slug, description=description,
            category_id=category_id or None, selling_price=selling_price,
            discount_price=discount_price or None,
            cost_price=selling_price, stock_qty=stock_qty, status=status,
        )
        for i, img in enumerate(request.FILES.getlist('images')):
            ProductImage.objects.create(product=product, image=img, is_primary=(i == 0), order=i)
        if video_file:
            ProductVideo.objects.create(
                product=product, video=video_file, thumbnail=video_thumb, title=video_title,
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
        delete_video_ids = request.POST.getlist('delete_videos')
        if delete_video_ids and 'name' not in request.POST:
            ProductVideo.objects.filter(product=product, pk__in=delete_video_ids).delete()
            messages.success(request, 'Video removed.')
            return redirect('vendors:dashboard')

        name           = request.POST.get('name', product.name).strip()
        selling_price  = request.POST.get('selling_price', product.selling_price)
        discount_price = request.POST.get('discount_price', '').strip()
        video_file     = request.FILES.get('video')
        video_title    = request.POST.get('video_title', '').strip()
        video_thumb    = request.FILES.get('video_thumbnail')

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

        product.name          = name
        product.description   = request.POST.get('description', '').strip()
        product.category_id   = request.POST.get('category_id') or None
        product.selling_price = selling_price
        product.discount_price = discount_price or None
        product.cost_price    = product.selling_price
        product.stock_qty     = request.POST.get('stock_qty', product.stock_qty)
        product.status        = request.POST.get('status', product.status)
        product.save()

        for i, img in enumerate(request.FILES.getlist('images')):
            ProductImage.objects.create(
                product=product, image=img, order=product.images.count() + i
            )
        if video_file:
            ProductVideo.objects.create(
                product=product, video=video_file, thumbnail=video_thumb, title=video_title,
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


# ── VENDOR EARNINGS ──────────────────────────────────────────────────────────

@vendor_required
def earnings(request):
    vendor      = request.vendor
    earnings_qs = VendorEarning.objects.filter(
        vendor=vendor
    ).select_related('order').order_by('-created_at')

    total    = earnings_qs.aggregate(t=Sum('net_amount'))['t'] or 0
    pending  = earnings_qs.filter(status='pending').aggregate(t=Sum('net_amount'))['t'] or 0
    held     = earnings_qs.filter(status='held').aggregate(t=Sum('net_amount'))['t'] or 0
    paid_out = earnings_qs.filter(status='paid').aggregate(t=Sum('net_amount'))['t'] or 0

    return render(request, 'vendors/earnings.html', {
        'vendor':   vendor,
        'earnings': earnings_qs,
        'total':    total,
        'pending':  pending,
        'held':     held,
        'paid_out': paid_out,
    })


# ── ANALYTICS DASHBOARD (item 11 from session) ───────────────────────────────

@vendor_required
def vendor_analytics(request):
    """
    Sales analytics dashboard.
    GET /vendors/vendor/dashboard/analytics/
    Cached 5 minutes per vendor to reduce DB load.
    """
    vendor    = request.vendor
    cache_key = f'vendor_analytics_{vendor.pk}'
    data      = cache.get(cache_key)

    if not data:
        now         = timezone.now()
        thirty_ago  = now - timedelta(days=30)
        seven_ago   = now - timedelta(days=7)

        paid_items = OrderItem.objects.filter(
            product__vendor=vendor,
            order__payment_status='paid',
        ).select_related('order', 'product')

        # Revenue by day — last 30 days
        daily = list(
            paid_items
            .filter(order__created_at__gte=thirty_ago)
            .annotate(day=TruncDate('order__created_at'))
            .values('day')
            .annotate(revenue=Sum('subtotal'), orders=Count('order', distinct=True))
            .order_by('day')
        )

        # Top 5 products by revenue
        top_products = list(
            paid_items
            .filter(order__created_at__gte=thirty_ago)
            .values('product__name', 'product__pk')
            .annotate(revenue=Sum('subtotal'), qty=Sum('quantity'))
            .order_by('-revenue')[:5]
        )

        # Peak order hours — last 7 days
        peak_hours = list(
            paid_items
            .filter(order__created_at__gte=seven_ago)
            .annotate(hour=TruncHour('order__created_at'))
            .values('hour')
            .annotate(count=Count('order', distinct=True))
            .order_by('hour')
        )

        # Totals
        total_revenue  = float(paid_items.aggregate(t=Sum('subtotal'))['t'] or 0)
        total_orders   = paid_items.values('order').distinct().count()
        avg_order_val  = float(
            paid_items
            .filter(order__created_at__gte=thirty_ago)
            .values('order')
            .annotate(ov=Sum('subtotal'))
            .aggregate(avg=Avg('ov'))['avg'] or 0
        )
        commission_paid = float(
            VendorEarning.objects
            .filter(vendor=vendor)
            .aggregate(t=Sum('commission_amount'))['t'] or 0
        )

        data = {
            'daily':           [
                {'day': str(d['day']), 'revenue': float(d['revenue'] or 0), 'orders': d['orders']}
                for d in daily
            ],
            'top_products':    [
                {'name': p['product__name'], 'revenue': float(p['revenue'] or 0), 'qty': p['qty']}
                for p in top_products
            ],
            'peak_hours':      [
                {'hour': str(h['hour']), 'count': h['count']}
                for h in peak_hours
            ],
            'total_revenue':   total_revenue,
            'total_orders':    total_orders,
            'avg_order_value': avg_order_val,
            'commission_paid': commission_paid,
            'net_revenue':     total_revenue - commission_paid,
        }
        cache.set(cache_key, data, 300)   # cache 5 minutes

    return render(request, 'vendors/analytics.html', {
        'vendor':     vendor,
        'data':       data,
        'cart_count': 0,
    })


# ── REFERRAL SYSTEM (item 12) ────────────────────────────────────────────────

def referral_landing(request, code):
    """
    /ref/<code>/ — Public. Records click, sets cookie, redirects to home.
    The cookie is read by _apply_referral_on_signup() when a new user registers.
    """
    try:
        from .models import Referral
        ref        = Referral.objects.get(code=code)
        ref.clicks = (ref.clicks or 0) + 1
        ref.save(update_fields=['clicks'])
    except Exception:
        pass
    response = redirect('frontend:home')
    response.set_cookie('ref_code', code, max_age=30 * 24 * 3600)  # 30 days
    return response


@login_required
def referral_stats(request):
    """GET /vendors/vendor/referrals/ — vendor sees their link + click/conversion counts."""
    from .models import Referral
    ref, _ = Referral.objects.get_or_create(
        referrer=request.user,
        defaults={'code': uuid.uuid4().hex[:8].upper()},
    )
    link = request.build_absolute_uri(reverse('vendors:referral_landing', args=[ref.code]))
    return render(request, 'vendors/referral.html', {
        'ref':        ref,
        'link':       link,
        'cart_count': 0,
    })


@login_required
def generate_referral(request):
    """POST /vendors/vendor/referrals/generate/ — returns JSON with link."""
    from .models import Referral
    ref, _ = Referral.objects.get_or_create(
        referrer=request.user,
        defaults={'code': uuid.uuid4().hex[:8].upper()},
    )
    link = request.build_absolute_uri(reverse('vendors:referral_landing', args=[ref.code]))
    return JsonResponse({'link': link, 'code': ref.code, 'clicks': ref.clicks or 0})


def _apply_referral_on_signup(user, request):
    """Called after vendor (or customer) registers — credits referrer if cookie present."""
    code = request.COOKIES.get('ref_code', '')
    if not code:
        return
    try:
        from .models import Referral
        ref              = Referral.objects.get(code=code)
        ref.conversions  = (ref.conversions or 0) + 1
        ref.save(update_fields=['conversions'])
    except Exception:
        pass


# ── VENDOR DISPATCH (manual rider assignment) ────────────────────────────────

@vendor_required
def dispatch_ride(request):
    from delivery.models import Delivery
    from delivery.views import _push_prompt_to_rider
    from rider.models import RiderProfile, DeliveryAcceptance
    from rider.views import notify_rider

    vendor = request.vendor

    pending_deliveries = (
        Delivery.objects
        .filter(order__items__product__vendor=vendor, status=Delivery.Status.PENDING)
        .select_related('order', 'zone')
        .distinct()
    )
    available_riders = (
        RiderProfile.objects
        .filter(status=RiderProfile.Status.AVAILABLE)
        .select_related('rider', 'zone')
    )

    if request.method == 'POST':
        delivery = get_object_or_404(Delivery, pk=request.POST.get('delivery_id'))
        rider    = get_object_or_404(RiderProfile, pk=request.POST.get('rider_id'))

        acceptance, created = DeliveryAcceptance.objects.get_or_create(
            delivery=delivery,
            defaults={'rider': rider, 'status': DeliveryAcceptance.Status.PENDING},
        )
        if not created:
            acceptance.rider        = rider
            acceptance.status       = DeliveryAcceptance.Status.PENDING
            acceptance.responded_at = None
            acceptance.save()

        _push_prompt_to_rider(rider, delivery, acceptance)
        notify_rider(
            rider.rider, 'New Delivery Request',
            f'Vendor dispatch — Pickup: {delivery.pickup_location or delivery.order.delivery_address}',
            notif_type='new_delivery', link='/rider/',
        )

        messages.success(request,
            f'Request sent to {rider.rider.get_full_name() or rider.rider.phone}. '
            'They\'ll accept or reject shortly.')
        return redirect('vendors:dispatch')

    return render(request, 'vendors/dispatch.html', {
        'pending_deliveries': pending_deliveries,
        'available_riders':   available_riders,
    })


# ── HELPER ───────────────────────────────────────────────────────────────────

def _get_cart_count(request):
    if request.user.is_authenticated:
        try:
            return request.user.cart.total_items
        except Exception:
            return 0
    return 0
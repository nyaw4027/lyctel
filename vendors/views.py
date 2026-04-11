from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Sum, Count, Q
from django.utils.text import slugify
from django.utils import timezone

from products.models import Product, Category, ProductImage
from order.models import Order, OrderItem
from .models import Vendor, VendorEarning


# ── Guard decorator ───────────────────────────────────────
def vendor_required(view_func):
    @login_required
    def wrapper(request, *args, **kwargs):
        try:
            vendor = request.user.vendor
            if vendor.status != Vendor.Status.ACTIVE:
                messages.warning(request,
                    'Your vendor account is pending approval. '
                    'We will notify you once approved.')
                return redirect('frontend:home')
            request.vendor = vendor
        except Vendor.DoesNotExist:
            messages.info(request, 'Apply to become a vendor first.')
            return redirect('vendors:apply')
        return view_func(request, *args, **kwargs)
    return wrapper


# ── APPLY TO BECOME A VENDOR ─────────────────────────────

def apply(request):
    """Public vendor application form."""
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

        # Auth fields (if not logged in)
        first_name = request.POST.get('first_name', '').strip()
        last_name  = request.POST.get('last_name', '').strip()
        password   = request.POST.get('password', '')

        errors = {}
        if not shop_name:   errors['shop_name']   = 'Shop name is required.'
        if not phone:       errors['phone']       = 'Phone number is required.'
        if not momo_number: errors['momo_number'] = 'MoMo number is required for payouts.'

        if not request.user.is_authenticated:
            if not first_name: errors['first_name'] = 'First name is required.'
            if not password:   errors['password']   = 'Password is required.'
            if len(password) < 6: errors['password'] = 'Password must be at least 6 characters.'

            from ecommerce.models import User
            if User.objects.filter(phone=phone).exists():
                errors['phone'] = 'An account with this phone number already exists. Sign in first.'

        if errors:
            return render(request, 'vendors/apply.html', {
                'errors': errors, 'form_data': request.POST
            })

        # Create user account if not logged in
        if not request.user.is_authenticated:
            from ecommerce.models import User
            from django.contrib.auth import login
            user = User.objects.create_user(
                username   = phone,
                phone      = phone,
                password   = password,
                first_name = first_name,
                last_name  = last_name,
                role       = 'customer',
            )
            login(request, user)
        else:
            user = request.user

        vendor = Vendor.objects.create(
            owner        = user,
            shop_name    = shop_name,
            description  = description,
            phone        = phone,
            location     = location,
            momo_number  = momo_number,
            momo_network = momo_network,
            status       = Vendor.Status.PENDING,
        )

        # Handle logo upload
        if 'logo' in request.FILES:
            vendor.logo = request.FILES['logo']
            vendor.save()

        messages.success(request,
            f'Application submitted! We will review "{shop_name}" and notify you shortly.')
        return redirect('vendors:pending')

    return render(request, 'vendors/apply.html', {})


@login_required
def pending(request):
    """Show pending approval status."""
    try:
        vendor = request.user.vendor
    except Vendor.DoesNotExist:
        return redirect('vendors:apply')
    return render(request, 'vendors/pending.html', {'vendor': vendor})


# ── VENDOR DASHBOARD ──────────────────────────────────────

@vendor_required
def dashboard(request):
    vendor = request.vendor

    products = vendor.products.prefetch_related('images').order_by('-created_at')
    earnings = VendorEarning.objects.filter(vendor=vendor)

    total_revenue  = earnings.aggregate(t=Sum('net_amount'))['t'] or 0
    pending_payout = earnings.filter(status='pending').aggregate(t=Sum('net_amount'))['t'] or 0
    total_orders   = earnings.count()

    recent_orders = OrderItem.objects.filter(
        product__vendor=vendor,
        order__payment_status='paid',
    ).select_related('order', 'product').order_by('-order__created_at')[:10]

    return render(request, 'vendors/dashboard.html', {
        'vendor':        vendor,
        'products':      products,
        'total_revenue': total_revenue,
        'pending_payout': pending_payout,
        'total_orders':  total_orders,
        'recent_orders': recent_orders,
        'cart_count':    0,
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
                'categories': categories, 'errors': errors,
                'form_data': request.POST, 'action': 'Add',
            })

        base_slug = slugify(name)
        slug, n = base_slug, 1
        while Product.objects.filter(slug=slug).exists():
            slug = f"{base_slug}-{n}"; n += 1

        product = Product.objects.create(
            vendor        = vendor,
            name          = name,
            slug          = slug,
            description   = description,
            category_id   = category_id or None,
            cost_price    = selling_price,   # vendor doesn't expose cost
            selling_price = selling_price,
            stock_qty     = stock_qty,
            status        = status,
        )

        for i, img in enumerate(request.FILES.getlist('images')):
            ProductImage.objects.create(
                product=product, image=img, is_primary=(i == 0), order=i
            )

        messages.success(request, f'"{product.name}" added successfully.')
        return redirect('vendors:dashboard')

    return render(request, 'vendors/product_form.html', {
        'categories': categories, 'action': 'Add',
    })


@vendor_required
def product_edit(request, pk):
    vendor  = request.vendor
    product = get_object_or_404(Product, pk=pk, vendor=vendor)
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
                product=product, image=img,
                order=product.images.count() + i
            )

        messages.success(request, f'"{product.name}" updated.')
        return redirect('vendors:dashboard')

    return render(request, 'vendors/product_form.html', {
        'product': product, 'categories': categories, 'action': 'Edit',
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


# ── PUBLIC VENDOR SHOP PAGE ───────────────────────────────

def shop_page(request, slug):
    """Public storefront for a vendor."""
    vendor   = get_object_or_404(Vendor, slug=slug, status=Vendor.Status.ACTIVE)
    products = vendor.products.filter(status='active').prefetch_related('images')

    search = request.GET.get('q', '').strip()
    if search:
        products = products.filter(
            Q(name__icontains=search) | Q(description__icontains=search)
        )

    from cart.models import Cart
    cart_count = 0
    if request.user.is_authenticated:
        try:
            cart_count = request.user.cart.total_items
        except Exception:
            pass

    return render(request, 'vendors/shop.html', {
        'vendor':     vendor,
        'products':   products,
        'search':     search,
        'cart_count': cart_count,
    })


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




    """
Add these two WhatsApp triggers to your existing vendors/views.py:

1. In the apply() view — after Vendor.objects.create(...)
2. In the vendor_detail() dashboard view — after vendor.status = ACTIVE
"""

# ── In apply() view, after vendor is created ──────────────
# Add this block right after vendor.save() at the end of the create section:

"""
# Notify admin of new vendor application
try:
    from notifications.whatsapp import notify_admin_vendor_applied
    notify_admin_vendor_applied(vendor)
except Exception:
    pass
"""


# ── In dashboard vendor_detail() view, after action == 'approve' ──
# Add this block right after vendor.save():

"""
# Notify vendor they've been approved
try:
    from notifications.whatsapp import notify_vendor_approved
    notify_vendor_approved(vendor)
except Exception:
    pass
"""


# ── In dashboard vendor_detail() view, after action == 'assign_rider' ──
# Add this block in dashboard/views.py after Delivery.objects.create():

"""
# Notify rider of new delivery assignment
try:
    from notifications.whatsapp import notify_rider_assigned
    notify_rider_assigned(delivery)  # delivery is the newly created Delivery object
except Exception:
    pass
"""
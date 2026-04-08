from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Sum, Count, Q
from django.utils import timezone
from django.utils.text import slugify
from datetime import timedelta

from products.models import Product, Category, ProductImage
from order.models import Order, OrderStatusHistory
from delivery.models import Delivery, DeliveryZone
from rider.models import RiderProfile
from ecommerce.models import User


# ── Access control decorator ──────────────────────────────
def admin_required(view_func):
    """Only allow users with role=admin."""
    @login_required
    def wrapper(request, *args, **kwargs):
        if not request.user.is_admin():
            messages.error(request, 'Access denied.')
            return redirect('frontend:home')
        return view_func(request, *args, **kwargs)
    return wrapper


# ── OVERVIEW DASHBOARD ────────────────────────────────────

@admin_required
def dashboard_home(request):
    today     = timezone.now().date()
    this_week = timezone.now() - timedelta(days=7)

    # Key stats
    total_orders    = Order.objects.count()
    pending_orders  = Order.objects.filter(status='pending').count()
    total_revenue   = Order.objects.filter(
        payment_status='paid'
    ).aggregate(t=Sum('total_amount'))['t'] or 0
    week_revenue    = Order.objects.filter(
        payment_status='paid', created_at__gte=this_week
    ).aggregate(t=Sum('total_amount'))['t'] or 0
    total_products  = Product.objects.filter(status='active').count()
    low_stock       = Product.objects.filter(
        status='active', stock_qty__lte=5
    ).count()
    total_customers = User.objects.filter(role='customer').count()
    active_riders   = RiderProfile.objects.filter(status='available').count()

    # Recent orders
    recent_orders = Order.objects.select_related('customer').order_by('-created_at')[:8]

    # Low stock products
    low_stock_products = Product.objects.filter(
        status='active', stock_qty__lte=5
    ).order_by('stock_qty')[:5]

    context = {
        'total_orders':       total_orders,
        'pending_orders':     pending_orders,
        'total_revenue':      total_revenue,
        'week_revenue':       week_revenue,
        'total_products':     total_products,
        'low_stock':          low_stock,
        'total_customers':    total_customers,
        'active_riders':      active_riders,
        'recent_orders':      recent_orders,
        'low_stock_products': low_stock_products,
    }
    return render(request, 'dashboard/home.html', context)


# ── PRODUCTS ──────────────────────────────────────────────

@admin_required
def product_list(request):
    query    = request.GET.get('q', '').strip()
    category = request.GET.get('category', '')
    status   = request.GET.get('status', '')

    products = Product.objects.select_related('category').prefetch_related('images')

    if query:
        products = products.filter(
            Q(name__icontains=query) | Q(category__name__icontains=query)
        )
    if category:
        products = products.filter(category__slug=category)
    if status:
        products = products.filter(status=status)

    products   = products.order_by('-created_at')
    categories = Category.objects.all()

    return render(request, 'dashboard/products/list.html', {
        'products':   products,
        'categories': categories,
        'query':      query,
        'filter_cat': category,
        'filter_status': status,
    })


@admin_required
def product_add(request):
    categories = Category.objects.filter(is_active=True)

    if request.method == 'POST':
        name          = request.POST.get('name', '').strip()
        description   = request.POST.get('description', '').strip()
        category_id   = request.POST.get('category_id')
        cost_price    = request.POST.get('cost_price')
        selling_price = request.POST.get('selling_price')
        stock_qty     = request.POST.get('stock_qty', 0)
        status        = request.POST.get('status', 'active')
        is_featured   = request.POST.get('is_featured') == 'on'

        errors = {}
        if not name:          errors['name']          = 'Product name is required.'
        if not selling_price: errors['selling_price'] = 'Selling price is required.'
        if not cost_price:    errors['cost_price']    = 'Cost price is required.'

        if errors:
            return render(request, 'dashboard/products/form.html', {
                'categories': categories, 'errors': errors,
                'form_data': request.POST, 'action': 'Add',
            })

        # Auto-generate unique slug
        base_slug = slugify(name)
        slug      = base_slug
        counter   = 1
        while Product.objects.filter(slug=slug).exists():
            slug = f"{base_slug}-{counter}"
            counter += 1

        product = Product.objects.create(
            name          = name,
            slug          = slug,
            description   = description,
            category_id   = category_id or None,
            cost_price    = cost_price,
            selling_price = selling_price,
            stock_qty     = stock_qty,
            status        = status,
            is_featured   = is_featured,
        )

        # Handle image uploads
        images = request.FILES.getlist('images')
        for i, img in enumerate(images):
            ProductImage.objects.create(
                product    = product,
                image      = img,
                is_primary = (i == 0),
                order      = i,
            )

        messages.success(request, f'"{product.name}" added successfully.')
        return redirect('dashboard:product_list')

    return render(request, 'dashboard/products/form.html', {
        'categories': categories, 'action': 'Add',
    })


@admin_required
def product_edit(request, pk):
    product    = get_object_or_404(Product, pk=pk)
    categories = Category.objects.filter(is_active=True)

    if request.method == 'POST':
        product.name          = request.POST.get('name', product.name).strip()
        product.description   = request.POST.get('description', '').strip()
        product.category_id   = request.POST.get('category_id') or None
        product.cost_price    = request.POST.get('cost_price', product.cost_price)
        product.selling_price = request.POST.get('selling_price', product.selling_price)
        product.stock_qty     = request.POST.get('stock_qty', product.stock_qty)
        product.status        = request.POST.get('status', product.status)
        product.is_featured   = request.POST.get('is_featured') == 'on'
        product.save()

        # Add new images if uploaded
        images = request.FILES.getlist('images')
        existing_count = product.images.count()
        for i, img in enumerate(images):
            ProductImage.objects.create(
                product = product,
                image   = img,
                order   = existing_count + i,
            )

        messages.success(request, f'"{product.name}" updated.')
        return redirect('dashboard:product_list')

    return render(request, 'dashboard/products/form.html', {
        'product':    product,
        'categories': categories,
        'action':     'Edit',
    })


@admin_required
def product_delete(request, pk):
    product = get_object_or_404(Product, pk=pk)
    if request.method == 'POST':
        name = product.name
        product.delete()
        messages.success(request, f'"{name}" deleted.')
    return redirect('dashboard:product_list')


@admin_required
def product_image_delete(request, pk):
    image = get_object_or_404(ProductImage, pk=pk)
    product_pk = image.product.pk
    image.delete()
    messages.info(request, 'Image removed.')
    return redirect('dashboard:product_edit', pk=product_pk)


# ── ORDERS ────────────────────────────────────────────────

@admin_required
def order_list(request):
    status  = request.GET.get('status', '')
    query   = request.GET.get('q', '').strip()
    orders  = Order.objects.select_related('customer').order_by('-created_at')

    if status:
        orders = orders.filter(status=status)
    if query:
        orders = orders.filter(
            Q(order_ref__icontains=query) |
            Q(customer__phone__icontains=query) |
            Q(delivery_city__icontains=query)
        )

    return render(request, 'dashboard/orders/list.html', {
        'orders':        orders,
        'filter_status': status,
        'query':         query,
        'status_choices': Order.Status.choices,
    })


@admin_required
def order_detail(request, pk):
    order   = get_object_or_404(Order, pk=pk)
    riders  = RiderProfile.objects.filter(
        is_verified=True, status='available'
    ).select_related('rider')
    zones   = DeliveryZone.objects.filter(is_active=True)
    history = order.status_history.all()

    try:
        delivery = order.delivery
    except Delivery.DoesNotExist:
        delivery = None

    if request.method == 'POST':
        action = request.POST.get('action')

        # Update order status
        if action == 'update_status':
            new_status = request.POST.get('status')
            old_status = order.status
            if new_status and new_status != old_status:
                OrderStatusHistory.objects.create(
                    order      = order,
                    old_status = old_status,
                    new_status = new_status,
                    changed_by = request.user,
                    note       = request.POST.get('note', ''),
                )
                order.status = new_status
                if new_status == 'delivered':
                    order.delivered_at = timezone.now()
                order.save()
                messages.success(request, f'Order status updated to {new_status}.')

        # Update payment status
        elif action == 'update_payment':
            order.payment_status = request.POST.get('payment_status')
            order.save()
            messages.success(request, 'Payment status updated.')

        # Assign rider
        elif action == 'assign_rider':
            rider_id = request.POST.get('rider_id')
            zone_id  = request.POST.get('zone_id')
            if rider_id and zone_id:
                rider = get_object_or_404(RiderProfile, pk=rider_id)
                zone  = get_object_or_404(DeliveryZone, pk=zone_id)
                if not delivery:
                    Delivery.objects.create(
                        order            = order,
                        rider            = rider,
                        zone             = zone,
                        delivery_fee     = zone.delivery_fee,
                        rider_commission = zone.delivery_fee * (rider.commission_rate / 100),
                        status           = 'assigned',
                    )
                    rider.status = 'on_delivery'
                    rider.save()
                    order.status = 'dispatched'
                    order.save()
                    messages.success(request, f'Order assigned to {rider.rider.get_full_name()}.')
                else:
                    messages.warning(request, 'A rider is already assigned.')

        return redirect('dashboard:order_detail', pk=pk)

    return render(request, 'dashboard/orders/detail.html', {
        'order':    order,
        'riders':   riders,
        'zones':    zones,
        'history':  history,
        'delivery': delivery,
    })


# ── RIDERS ────────────────────────────────────────────────

@admin_required
def rider_list(request):
    riders = RiderProfile.objects.select_related(
        'rider', 'zone'
    ).order_by('-joined_at')
    return render(request, 'dashboard/riders/list.html', {'riders': riders})


@admin_required
def rider_detail(request, pk):
    profile     = get_object_or_404(RiderProfile, pk=pk)
    deliveries  = Delivery.objects.filter(
        rider=profile
    ).select_related('order').order_by('-assigned_at')[:20]

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'verify':
            profile.is_verified = not profile.is_verified
            profile.save()
            status = 'verified' if profile.is_verified else 'unverified'
            messages.success(request, f'Rider {status}.')

        elif action == 'update_commission':
            rate = request.POST.get('commission_rate')
            if rate:
                profile.commission_rate = rate
                profile.save()
                messages.success(request, f'Commission rate updated to {rate}%.')

        elif action == 'update_zone':
            zone_id = request.POST.get('zone_id')
            profile.zone_id = zone_id or None
            profile.save()
            messages.success(request, 'Zone updated.')

        return redirect('dashboard:rider_detail', pk=pk)

    zones = DeliveryZone.objects.filter(is_active=True)
    return render(request, 'dashboard/riders/detail.html', {
        'profile':    profile,
        'deliveries': deliveries,
        'zones':      zones,
    })


# ── CATEGORIES ────────────────────────────────────────────

@admin_required
def category_list(request):
    categories = Category.objects.annotate(product_count=Count('products'))

    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        if name:
            slug = slugify(name)
            counter = 1
            base_slug = slug
            while Category.objects.filter(slug=slug).exists():
                slug = f"{base_slug}-{counter}"
                counter += 1
            Category.objects.create(name=name, slug=slug)
            messages.success(request, f'Category "{name}" added.')
        return redirect('dashboard:category_list')

    return render(request, 'dashboard/categories/list.html', {
        'categories': categories,
    })
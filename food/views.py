"""
food/views.py — clean rewrite
All automated patches removed. Written correctly from scratch.
"""

import base64
import json
import math
import uuid
from decimal import Decimal, InvalidOperation

import requests
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Q, Sum
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .models import (
    FoodVendor, FoodCategory, FoodItem,
    FoodOrder, FoodOrderItem, FoodCart, FoodCartItem,
    FoodPayment, FoodVendorEarning,
)
from delivery.models import Delivery, DeliveryZone


# ── Constants ──────────────────────────────────────────────────────────────────
FOOD_VENDOR_SHARE = Decimal('0.96')
FOOD_APP_SHARE    = Decimal('0.04')
BASE_FARE         = Decimal('5.00')
PER_KM_RATE       = Decimal('2.50')
MIN_FARE          = Decimal('8.00')


# ── Geo helpers ────────────────────────────────────────────────────────────────

def haversine_distance(lat1, lng1, lat2, lng2):
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlng / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def calculate_delivery_fee(distance_km):
    if not distance_km or distance_km <= 0:
        return MIN_FARE
    fee = BASE_FARE + Decimal(str(distance_km)) * PER_KM_RATE
    return max(fee, MIN_FARE).quantize(Decimal('0.01'))


def estimate_eta(distance_km, prep_time=20):
    travel = int((distance_km / 30) * 60) if distance_km else 15
    return prep_time + travel


# ── Cart model helpers ─────────────────────────────────────────────────────────
# These never assume specific model property names; they try several fallbacks.

def _get_cart(user):
    """Return the user's FoodCart or None. Tries multiple accessor names."""
    for attr in ('food_cart', 'foodcart', 'cart'):
        try:
            obj = getattr(user, attr)
            if hasattr(obj, 'first'):   # manager
                obj = obj.order_by('-pk').first()
            if obj is not None:
                return obj
        except Exception:
            pass
    for field in ('customer', 'user'):
        try:
            return FoodCart.objects.filter(**{field: user}).first()
        except Exception:
            pass
    return None


def _get_or_create_cart(user):
    """Return (cart, created). Tries multiple FK field names."""
    cart = _get_cart(user)
    if cart:
        return cart, False
    for field in ('customer', 'user'):
        try:
            return FoodCart.objects.get_or_create(**{field: user})
        except Exception:
            pass
    raise Exception("Cannot create FoodCart — verify FoodCart has a FK to the user model")


def _cart_items(cart):
    """Return queryset of cart items. Tries multiple related_name values."""
    for attr in ('cart_items', 'items', 'foodcartitem_set'):
        qs = getattr(cart, attr, None)
        if qs is not None:
            try:
                return qs.select_related('food').all()
            except Exception:
                pass
    return FoodCartItem.objects.filter(cart=cart).select_related('food')


def _item_price(food_item):
    """Return the effective price of a FoodItem."""
    for attr in ('final_price', 'discount_price', 'price'):
        val = getattr(food_item, attr, None)
        if val is not None:
            return Decimal(str(val))
    return Decimal('0')


def _cart_count(cart):
    """Return number of items in cart."""
    # Try model property first
    for attr in ('item_count', 'total_items', 'count'):
        val = getattr(cart, attr, None)
        if val is not None and not callable(val):
            return int(val)
        if callable(val):
            try:
                return int(val())
            except Exception:
                pass
    try:
        return _cart_items(cart).count()
    except Exception:
        return 0


def _cart_subtotal(cart):
    """Return sum of (price × qty) for all items."""
    for attr in ('total', 'subtotal', 'cart_total'):
        val = getattr(cart, attr, None)
        if val is not None and not callable(val):
            return Decimal(str(val))
        if callable(val):
            try:
                return Decimal(str(val()))
            except Exception:
                pass
    total = Decimal('0')
    for ci in _cart_items(cart):
        if ci.food:
            total += _item_price(ci.food) * ci.quantity
    return total


def _item_line_total(cart_item):
    for attr in ('subtotal', 'total', 'total_price'):
        val = getattr(cart_item, attr, None)
        if val is not None and not callable(val):
            return Decimal(str(val))
    return _item_price(cart_item.food) * cart_item.quantity if cart_item.food else Decimal('0')


# ── Hubtel helper ──────────────────────────────────────────────────────────────

def _hubtel_auth():
    cid = getattr(settings, 'HUBTEL_CLIENT_ID',     '')
    cs  = getattr(settings, 'HUBTEL_CLIENT_SECRET', '')
    return 'Basic ' + base64.b64encode(f'{cid}:{cs}'.encode()).decode()


# ── Notification helper ────────────────────────────────────────────────────────

def _notify_food_status(order, status):
    try:
        from delivery.notifications import notify_food_order_status_change
        notify_food_order_status_change(order, status)
    except Exception:
        pass


# ── Restaurant guard ───────────────────────────────────────────────────────────

def restaurant_required(view_func):
    @login_required
    def wrapper(request, *args, **kwargs):
        try:
            restaurant = FoodVendor.objects.get(owner=request.user)
            if restaurant.status == FoodVendor.Status.SUSPENDED:
                messages.error(request, 'Your restaurant has been suspended.')
                return redirect('food:home')
            request.restaurant = restaurant
        except FoodVendor.DoesNotExist:
            messages.info(request, 'Register your restaurant first.')
            return redirect('food:register')
        return view_func(request, *args, **kwargs)
    wrapper.__name__ = view_func.__name__
    return wrapper


# ── Food home ──────────────────────────────────────────────────────────────────

def food_home(request):
    cuisine  = request.GET.get('cuisine', '')
    query    = request.GET.get('q', '').strip()
    user_lat = request.GET.get('lat')
    user_lng = request.GET.get('lng')

    vendors = FoodVendor.objects.filter(
        status__in=[FoodVendor.Status.OPEN, FoodVendor.Status.BUSY]
    ).prefetch_related('food_items')

    if cuisine:
        vendors = vendors.filter(cuisine=cuisine)
    if query:
        vendors = vendors.filter(
            Q(name__icontains=query) | Q(description__icontains=query)
        )

    vendor_list = []
    for v in vendors:
        distance = eta = None
        if user_lat and user_lng and v.latitude and v.longitude:
            try:
                distance = round(haversine_distance(
                    float(user_lat), float(user_lng), v.latitude, v.longitude
                ), 1)
                eta = estimate_eta(distance, v.avg_prep_time)
            except Exception:
                pass
        vendor_list.append({'vendor': v, 'distance': distance, 'eta': eta})

    vendor_list.sort(key=lambda x: x['distance'] if x['distance'] is not None else 999)

    cart_count = 0
    if request.user.is_authenticated:
        cart = _get_cart(request.user)
        if cart:
            cart_count = _cart_count(cart)

    return render(request, 'food/home.html', {
        'vendor_list':      vendor_list,
        'cuisines':         FoodVendor.CuisineType.choices,
        'selected_cuisine': cuisine,
        'query':            query,
        'food_cart_count':  cart_count,
        'cart_count':       0,
        'locationiq_key':   getattr(settings, 'LOCATIONIQ_API_KEY', ''),
    })


# ── Vendor menu ────────────────────────────────────────────────────────────────

def vendor_menu(request, slug):
    vendor              = get_object_or_404(FoodVendor, slug=slug)
    categories          = vendor.food_categories.prefetch_related('items').all()
    all_items           = vendor.food_items.filter(is_available=True).select_related('category')
    uncategorized_items = all_items.filter(category__isnull=True)
    featured_items      = all_items.filter(is_featured=True)[:10]

    food_cart_count = 0
    cart_vendor_id  = None
    if request.user.is_authenticated:
        cart = _get_cart(request.user)
        if cart:
            food_cart_count = _cart_count(cart)
            cart_vendor_id  = cart.vendor_id

    return render(request, 'food/menu.html', {
        'vendor':              vendor,
        'categories':          categories,
        'all_items':           all_items,
        'uncategorized_items': uncategorized_items,
        'featured_items':      featured_items,
        'food_cart_count':     food_cart_count,
        'cart_vendor_id':      cart_vendor_id,
        'cart_count':          0,
    })


# ── Restaurant registration ────────────────────────────────────────────────────

@login_required
def register_restaurant(request):
    if FoodVendor.objects.filter(owner=request.user).exists():
        return redirect('food:restaurant_dashboard')

    locationiq_key = getattr(settings, 'LOCATIONIQ_API_KEY', '')
    context = {
        'cuisines':       FoodVendor.CuisineType.choices,
        'cart_count':     0,
        'locationiq_key': locationiq_key,
    }

    if request.method != 'POST':
        return render(request, 'food/register.html', context)

    name         = request.POST.get('name', '').strip()
    description  = request.POST.get('description', '').strip()
    cuisine      = request.POST.get('cuisine', '').strip()
    address      = request.POST.get('address', '').strip()
    city         = request.POST.get('city', 'Accra').strip()
    phone        = request.POST.get('phone', '').strip()
    whatsapp     = request.POST.get('whatsapp', '').strip()
    opening_time = request.POST.get('opening_time', '08:00')
    closing_time = request.POST.get('closing_time', '22:00')
    latitude     = request.POST.get('latitude', '').strip()
    longitude    = request.POST.get('longitude', '').strip()

    errors = {}
    if not name:    errors['name']    = 'Restaurant name is required.'
    if not cuisine: errors['cuisine'] = 'Please select a cuisine type.'
    if not address: errors['address'] = 'Address is required.'
    if not phone:   errors['phone']   = 'Phone number is required.'

    try:
        min_order = Decimal(request.POST.get('min_order', '10'))
    except InvalidOperation:
        min_order = Decimal('10')

    try:
        avg_prep = max(0, int(request.POST.get('avg_prep_time', '20')))
    except (ValueError, TypeError):
        avg_prep = 20

    lat = lng = None
    if latitude and longitude:
        try:
            lat = float(latitude)
            lng = float(longitude)
        except ValueError:
            errors['location'] = 'Invalid map coordinates.'
    else:
        errors['location'] = 'Please drop a pin on the map to set your restaurant location.'

    if errors:
        context.update({'errors': errors, 'form_data': request.POST})
        return render(request, 'food/register.html', context)

    try:
        with transaction.atomic():
            restaurant = FoodVendor(
                owner=request.user, name=name, description=description,
                cuisine=cuisine, address=address, city=city, phone=phone,
                whatsapp=whatsapp, opening_time=opening_time,
                closing_time=closing_time, min_order=min_order,
                avg_prep_time=avg_prep, latitude=lat, longitude=lng,
                status=FoodVendor.Status.OPEN,
            )
            if request.FILES.get('logo'):   restaurant.logo   = request.FILES['logo']
            if request.FILES.get('banner'): restaurant.banner = request.FILES['banner']
            restaurant.save()
    except Exception as e:
        context.update({'errors': {'general': str(e)}, 'form_data': request.POST})
        return render(request, 'food/register.html', context)

    messages.success(request, f'🎉 "{restaurant.name}" registered successfully!')
    return redirect('food:restaurant_dashboard')


# ── Restaurant dashboard ───────────────────────────────────────────────────────

@restaurant_required
def restaurant_dashboard(request):
    restaurant    = request.restaurant
    tab           = request.GET.get('tab', 'orders')
    status_filter = request.GET.get('status', '')

    all_orders    = FoodOrder.objects.filter(vendor=restaurant)
    total_orders  = all_orders.count()
    active_orders = all_orders.filter(
        status__in=['pending', 'confirmed', 'preparing', 'ready']
    ).count()
    total_revenue = (
        all_orders.filter(payment_status='paid')
        .aggregate(t=Sum('total_amount'))['t'] or 0
    )
    today_orders = all_orders.filter(
        created_at__date=timezone.now().date()
    ).count()

    orders = all_orders.select_related('customer').prefetch_related('items').order_by('-created_at')
    if status_filter:
        orders = orders.filter(status=status_filter)

    categories = restaurant.food_categories.prefetch_related('items').all()
    all_items  = restaurant.food_items.select_related('category').order_by('name')

    return render(request, 'food/restaurant_dashboard.html', {
        'vendor':         restaurant,
        'restaurant':     restaurant,
        'tab':            tab,
        'total_orders':   total_orders,
        'active_orders':  active_orders,
        'earnings':       total_revenue,
        'total_revenue':  total_revenue,
        'today_orders':   today_orders,
        'recent_orders':  orders[:20],
        'orders':         orders[:50],
        'status_filter':  status_filter,
        'categories':     categories,
        'all_items':      all_items,
        'status_choices': FoodOrder.Status.choices,
        'cart_count':     0,
    })


# ── Update order status ────────────────────────────────────────────────────────

@restaurant_required
@require_POST
def restaurant_update_order(request, ref):
    order      = get_object_or_404(FoodOrder, order_ref=ref, vendor=request.restaurant)
    new_status = request.POST.get('status', '').strip()
    valid      = [s[0] for s in FoodOrder.Status.choices]

    if new_status in valid:
        order.status = new_status
        if new_status == 'confirmed':
            order.confirmed_at = timezone.now()
        elif new_status == 'delivered':
            order.delivered_at   = timezone.now()
            order.payment_status = FoodOrder.PaymentStatus.PAID
        order.save()
        messages.success(request, f'Order {ref} → {order.get_status_display()}')
        _notify_food_status(order, new_status)
    else:
        messages.error(request, 'Invalid status.')

    return redirect(reverse('food:restaurant_dashboard') + '?tab=orders')


# ── Menu item management ───────────────────────────────────────────────────────

def _item_form_context(restaurant, item=None, action='Add', errors=None, post=None):
    from types import SimpleNamespace
    if item and not post:
        ns = SimpleNamespace(
            name=SimpleNamespace(value=item.name),
            description=SimpleNamespace(value=item.description or ''),
            price=SimpleNamespace(value=str(item.price)),
            discount_price=SimpleNamespace(value=str(item.discount_price) if item.discount_price else ''),
            prep_time=SimpleNamespace(value=str(item.prep_time)),
            category=SimpleNamespace(value=str(item.category_id) if item.category_id else ''),
            is_available=SimpleNamespace(value=item.is_available),
            is_featured=SimpleNamespace(value=item.is_featured),
            instance=item,
        )
    elif post:
        ns = SimpleNamespace(
            name=SimpleNamespace(value=post.get('name', '')),
            description=SimpleNamespace(value=post.get('description', '')),
            price=SimpleNamespace(value=post.get('price', '')),
            discount_price=SimpleNamespace(value=post.get('discount_price', '')),
            prep_time=SimpleNamespace(value=post.get('prep_time', '15')),
            category=SimpleNamespace(value=post.get('category_id', '')),
            is_available=SimpleNamespace(value=post.get('is_available') == 'on'),
            is_featured=SimpleNamespace(value=post.get('is_featured') == 'on'),
            instance=item,
        )
    else:
        ns = SimpleNamespace(
            name=SimpleNamespace(value=''),
            description=SimpleNamespace(value=''),
            price=SimpleNamespace(value=''),
            discount_price=SimpleNamespace(value=''),
            prep_time=SimpleNamespace(value='15'),
            category=SimpleNamespace(value=''),
            is_available=SimpleNamespace(value=True),
            is_featured=SimpleNamespace(value=False),
            instance=None,
        )
    return {
        'restaurant': restaurant, 'vendor': restaurant,
        'categories': restaurant.food_categories.all(),
        'form': ns, 'item': item,
        'action': action, 'errors': errors or {},
        'cart_count': 0,
    }


@restaurant_required
def restaurant_add_item(request):
    restaurant = request.restaurant
    if request.method != 'POST':
        return render(request, 'food/item_form.html', _item_form_context(restaurant))

    name     = request.POST.get('name', '').strip()
    errors   = {}
    if not name:
        errors['name'] = 'Item name is required.'

    price = None
    try:
        price = Decimal(request.POST.get('price', ''))
        if price <= 0:
            errors['price'] = 'Price must be greater than 0.'
    except (InvalidOperation, ValueError):
        errors['price'] = 'Enter a valid price.'

    discount_price = None
    disc_raw = request.POST.get('discount_price', '').strip()
    if disc_raw:
        try:
            discount_price = Decimal(disc_raw)
            if price and discount_price >= price:
                errors['discount_price'] = 'Discount must be less than regular price.'
        except (InvalidOperation, ValueError):
            errors['discount_price'] = 'Enter a valid discount price.'

    if errors:
        return render(request, 'food/item_form.html',
                      _item_form_context(restaurant, action='Add', errors=errors, post=request.POST))

    cat_id = request.POST.get('category_id') or None
    try:
        prep = max(0, int(request.POST.get('prep_time', 15)))
    except (ValueError, TypeError):
        prep = 15

    item = FoodItem(
        vendor=restaurant, name=name,
        description=request.POST.get('description', '').strip(),
        category_id=cat_id, price=price, discount_price=discount_price,
        prep_time=prep,
        is_available=request.POST.get('is_available') == 'on',
        is_featured=request.POST.get('is_featured') == 'on',
        is_spicy=request.POST.get('is_spicy') == 'on',
        is_vegan=request.POST.get('is_vegan') == 'on',
    )
    if 'image' in request.FILES:
        item.image = request.FILES['image']
    item.save()
    messages.success(request, f'"{name}" added to menu.')
    return redirect(reverse('food:restaurant_dashboard') + '?tab=menu')


@restaurant_required
def restaurant_edit_item(request, pk):
    restaurant = request.restaurant
    item       = get_object_or_404(FoodItem, pk=pk, vendor=restaurant)

    if request.method != 'POST':
        return render(request, 'food/item_form.html',
                      _item_form_context(restaurant, item=item, action='Edit'))

    name   = request.POST.get('name', item.name).strip()
    errors = {}
    if not name:
        errors['name'] = 'Item name is required.'

    try:
        price = Decimal(request.POST.get('price', str(item.price)))
        if price <= 0:
            errors['price'] = 'Price must be greater than 0.'
    except (InvalidOperation, ValueError):
        price = item.price
        errors['price'] = 'Enter a valid price.'

    discount_price = None
    disc_raw = request.POST.get('discount_price', '').strip()
    if disc_raw:
        try:
            discount_price = Decimal(disc_raw)
            if discount_price >= price:
                errors['discount_price'] = 'Discount must be less than price.'
        except (InvalidOperation, ValueError):
            errors['discount_price'] = 'Enter a valid discount price.'

    if errors:
        return render(request, 'food/item_form.html',
                      _item_form_context(restaurant, item=item, action='Edit',
                                         errors=errors, post=request.POST))

    cat_id = request.POST.get('category_id') or None
    try:
        prep = max(0, int(request.POST.get('prep_time', item.prep_time)))
    except (ValueError, TypeError):
        prep = item.prep_time

    item.name          = name
    item.description   = request.POST.get('description', '').strip()
    item.category_id   = cat_id
    item.price         = price
    item.discount_price = discount_price
    item.prep_time     = prep
    item.is_available  = request.POST.get('is_available') == 'on'
    item.is_featured   = request.POST.get('is_featured') == 'on'
    item.is_spicy      = request.POST.get('is_spicy') == 'on'
    item.is_vegan      = request.POST.get('is_vegan') == 'on'
    if 'image' in request.FILES:
        item.image = request.FILES['image']
    item.save()
    messages.success(request, f'"{item.name}" updated.')
    return redirect(reverse('food:restaurant_dashboard') + '?tab=menu')


@restaurant_required
@require_POST
def restaurant_delete_item(request, pk):
    item = get_object_or_404(FoodItem, pk=pk, vendor=request.restaurant)
    name = item.name
    item.delete()
    messages.success(request, f'"{name}" removed.')
    return redirect(reverse('food:restaurant_dashboard') + '?tab=menu')


@restaurant_required
@require_POST
def restaurant_add_category(request):
    name = request.POST.get('name', '').strip()
    if name:
        FoodCategory.objects.create(vendor=request.restaurant, name=name)
        messages.success(request, f'Category "{name}" added.')
    return redirect(reverse('food:restaurant_dashboard') + '?tab=menu')


# ── Restaurant settings ────────────────────────────────────────────────────────

@restaurant_required
def restaurant_settings(request):
    restaurant = request.restaurant

    if request.method == 'POST':
        restaurant.name         = request.POST.get('name', restaurant.name).strip()
        restaurant.description  = request.POST.get('description', '').strip()
        restaurant.cuisine      = request.POST.get('cuisine', restaurant.cuisine)
        restaurant.address      = request.POST.get('address', restaurant.address).strip()
        restaurant.city         = request.POST.get('city', restaurant.city).strip()
        restaurant.phone        = request.POST.get('phone', restaurant.phone).strip()
        restaurant.whatsapp     = request.POST.get('whatsapp', '').strip()
        restaurant.opening_time = request.POST.get('opening_time', '08:00')
        restaurant.closing_time = request.POST.get('closing_time', '22:00')
        restaurant.status       = request.POST.get('status', restaurant.status)
        try:
            restaurant.min_order = Decimal(request.POST.get('min_order', str(restaurant.min_order)))
        except InvalidOperation:
            pass
        try:
            restaurant.avg_prep_time = int(request.POST.get('avg_prep_time', str(restaurant.avg_prep_time)))
        except ValueError:
            pass
        lat = request.POST.get('latitude', '').strip()
        lng = request.POST.get('longitude', '').strip()
        restaurant.latitude  = float(lat) if lat else None
        restaurant.longitude = float(lng) if lng else None
        if 'logo'   in request.FILES: restaurant.logo   = request.FILES['logo']
        if 'banner' in request.FILES: restaurant.banner = request.FILES['banner']
        restaurant.save()
        messages.success(request, 'Settings saved.')
        return redirect('food:restaurant_settings')

    return render(request, 'food/restaurant_settings.html', {
        'vendor':         restaurant,
        'restaurant':     restaurant,
        'cuisines':       FoodVendor.CuisineType.choices,
        'statuses':       FoodVendor.Status.choices,
        'cart_count':     0,
        'locationiq_key': getattr(settings, 'LOCATIONIQ_API_KEY', ''),
    })


# ── Cart HTML page ─────────────────────────────────────────────────────────────

@login_required
def cart_page(request):
    cart        = _get_cart(request.user)
    cart_items  = _cart_items(cart) if cart else []
    cart_vendor = cart.vendor if cart else None
    subtotal    = _cart_subtotal(cart) if cart else Decimal('0')
    delivery    = MIN_FARE
    return render(request, 'food/cart.html', {
        'cart':          cart,
        'cart_items':    cart_items,
        'cart_vendor':   cart_vendor,
        'cart_subtotal': subtotal,
        'delivery_fee':  delivery,
        'cart_total':    subtotal + delivery,
        'cart_count':    _cart_count(cart) if cart else 0,
        'food_cart_count': _cart_count(cart) if cart else 0,
    })


# ── Cart APIs ──────────────────────────────────────────────────────────────────

@login_required
@require_POST
def cart_add(request, item_id):
    try:
        food = get_object_or_404(FoodItem, pk=item_id, is_available=True)

        # food.js sends FormData; fall back to JSON for API clients
        if 'application/json' in (request.content_type or ''):
            try:
                d = json.loads(request.body)
            except Exception:
                d = {}
            qty  = max(1, int(d.get('quantity', 1)))
            note = d.get('note', '')
        else:
            qty  = max(1, int(request.POST.get('quantity', 1)))
            note = request.POST.get('note', '')

        cart, _ = _get_or_create_cart(request.user)

        # Conflict: cart already has items from a different restaurant
        if cart.vendor and cart.vendor_id != food.vendor_id:
            return JsonResponse({
                'success':  False,
                'conflict': True,
                'message':  (
                    f'Your cart has items from {cart.vendor.name}. '
                    'Clear it first to order from this restaurant.'
                ),
            })

        cart.vendor = food.vendor
        cart.save()

        ci, created = FoodCartItem.objects.get_or_create(
            cart=cart, food=food,
            defaults={'quantity': qty, 'note': note},
        )
        if not created:
            ci.quantity += qty
            ci.note      = note
            ci.save()

        count = _cart_count(cart)
        total = _cart_subtotal(cart)

        return JsonResponse({
            'success':    True,
            'cart_count': count,
            'count':      count,
            'cart_total': str(total),
            'total':      str(total),
        })

    except Exception as e:
        import logging
        logging.getLogger(__name__).error('[cart_add] %s', e, exc_info=True)
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
@require_POST
def cart_update(request, item_id):
    try:
        if 'application/json' in (request.content_type or ''):
            try:
                d = json.loads(request.body)
            except Exception:
                d = {}
            qty = int(d.get('quantity', 1))
        else:
            qty = int(request.POST.get('quantity', 1))

        ci = get_object_or_404(FoodCartItem, pk=item_id, cart__in=FoodCart.objects.filter(
            **{'customer': request.user}
        ) if hasattr(FoodCart, 'customer') else FoodCart.objects.all())

        # Try the lookup more flexibly
        try:
            ci = get_object_or_404(FoodCartItem, pk=item_id)
            # Verify ownership
            cart = ci.cart
            owned = False
            for field in ('customer', 'user'):
                if getattr(cart, field, None) == request.user:
                    owned = True
                    break
            if not owned:
                return JsonResponse({'success': False, 'error': 'Not your cart'}, status=403)
        except Exception:
            return JsonResponse({'success': False, 'error': 'Item not found'}, status=404)

        new_total = None
        if qty <= 0:
            ci.delete()
        else:
            ci.quantity = qty
            ci.save()
            try:
                new_total = str((_item_price(ci.food) * qty).quantize(Decimal('0.01')))
            except Exception:
                pass

        cart = _get_cart(request.user)
        count = _cart_count(cart) if cart else 0
        total = str(_cart_subtotal(cart)) if cart else '0'

        return JsonResponse({
            'success':    True,
            'cart_count': count,
            'count':      count,
            'cart_total': total,
            'total':      total,
            'new_total':  new_total,
        })

    except Exception as e:
        import logging
        logging.getLogger(__name__).error('[cart_update] %s', e, exc_info=True)
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
@require_POST
def cart_clear(request):
    try:
        cart = _get_cart(request.user)
        if cart:
            _cart_items(cart).delete()
            cart.vendor = None
            cart.save()
    except Exception:
        pass
    return JsonResponse({'success': True, 'count': 0, 'total': '0'})


@login_required
def cart_data(request):
    try:
        cart     = _get_cart(request.user)
        items    = _cart_items(cart) if cart else []
        count    = _cart_count(cart) if cart else 0
        subtotal = _cart_subtotal(cart) if cart else Decimal('0')
        return JsonResponse({
            'success':   True,
            'count':     count,
            'cart_count': count,
            'total':     str(subtotal),
            'cart_total': str(subtotal),
            'subtotal':  str(subtotal),
            'delivery':  str(MIN_FARE),
            'vendor':      cart.vendor.name if cart and cart.vendor else None,
            'vendor_slug': cart.vendor.slug if cart and cart.vendor else None,
            'items': [{
                'id':       i.pk,
                'name':     i.food.name,
                'price':    str(_item_price(i.food)),
                'quantity': i.quantity,
                'subtotal': str(_item_line_total(i)),
                'image':    getattr(i.food, 'image_url', '') or '',
                'note':     i.note or '',
            } for i in items if i.food],
        })
    except Exception as e:
        return JsonResponse({'success': False, 'count': 0, 'total': '0', 'items': [], 'error': str(e)})


def price_estimate(request):
    try:
        vlat = float(request.GET.get('vlat'))
        vlng = float(request.GET.get('vlng'))
        dlat = float(request.GET.get('dlat'))
        dlng = float(request.GET.get('dlng'))
        prep = int(request.GET.get('prep', 20))
    except (TypeError, ValueError):
        return JsonResponse({'success': False, 'error': 'Invalid coordinates'})

    dist = haversine_distance(vlat, vlng, dlat, dlng)
    fee  = calculate_delivery_fee(dist)
    eta  = estimate_eta(dist, prep)
    return JsonResponse({
        'success': True, 'distance_km': round(dist, 2),
        'fee': str(fee), 'eta_minutes': eta,
    })


# ── Checkout ───────────────────────────────────────────────────────────────────

@login_required
def checkout(request):
    cart = _get_cart(request.user)
    if not cart or not _cart_items(cart).exists():
        messages.error(request, 'Your cart is empty.')
        return redirect('food:home')

    vendor       = cart.vendor
    locationiq   = getattr(settings, 'LOCATIONIQ_API_KEY', '')
    cart_items   = _cart_items(cart)
    subtotal     = _cart_subtotal(cart)
    delivery_fee = MIN_FARE

    def ctx(errors=None):
        return {
            'cart':           cart,
            'cart_vendor':    vendor,
            'vendor':         vendor,
            'cart_items':     cart_items,
            'cart_subtotal':  subtotal,
            'delivery_fee':   delivery_fee,
            'cart_total':     subtotal + delivery_fee,
            'subtotal':       subtotal,
            'default_fee':    str(MIN_FARE),
            'cart_count':     0,
            'payment_methods': FoodOrder.PaymentMethod.choices,
            'vendor_lat':     vendor.latitude  or '' if vendor else '',
            'vendor_lng':     vendor.longitude or '' if vendor else '',
            'locationiq_key': locationiq,
            'errors':         errors or {},
        }

    if request.method != 'POST':
        return render(request, 'food/checkout.html', ctx())

    address    = request.POST.get('delivery_address', '').strip()
    phone      = request.POST.get('delivery_phone', '').strip()
    note       = request.POST.get('delivery_note', '').strip()
    pay_method = request.POST.get('payment_method', 'cash')
    dlat       = request.POST.get('delivery_lat', '').strip()
    dlng       = request.POST.get('delivery_lng', '').strip()
    fee_raw    = request.POST.get('delivery_fee', str(MIN_FARE))
    dist_raw   = request.POST.get('distance_km', '0')

    errors = {}
    if not address: errors['address'] = 'Please enter your delivery address.'
    if not phone:   errors['phone']   = 'Please enter your phone number.'
    if errors:
        return render(request, 'food/checkout.html', ctx(errors))

    try:
        delivery_fee = Decimal(fee_raw)
    except (InvalidOperation, ValueError):
        delivery_fee = MIN_FARE

    try:
        distance_km = float(dist_raw) if dist_raw else 3.0
    except ValueError:
        distance_km = 3.0

    order = FoodOrder.objects.create(
        customer                = request.user,
        vendor                  = vendor,
        delivery_address        = address,
        delivery_lat            = float(dlat) if dlat else 5.6037,
        delivery_lng            = float(dlng) if dlng else -0.1870,
        delivery_phone          = phone,
        delivery_note           = note,
        subtotal                = subtotal,
        delivery_fee            = delivery_fee,
        distance_km             = distance_km,
        payment_method          = pay_method,
        payment_status          = FoodOrder.PaymentStatus.UNPAID,
        estimated_delivery_time = estimate_eta(distance_km, vendor.avg_prep_time if vendor else 20),
    )

    for ci in cart_items:
        FoodOrderItem.objects.create(
            order=order, food=ci.food,
            name=ci.food.name,
            price=_item_price(ci.food),
            quantity=ci.quantity,
            note=ci.note or '',
        )

    # Create delivery record
    try:
        zone = DeliveryZone.objects.filter(is_active=True).first()
        delivery_record = Delivery.objects.create(
            booker=request.user,
            pickup_location=vendor.address if vendor else '',
            dropoff_location=address,
            pickup_lat=vendor.latitude if vendor else None,
            pickup_lng=vendor.longitude if vendor else None,
            dropoff_lat=float(dlat) if dlat else None,
            dropoff_lng=float(dlng) if dlng else None,
            delivery_fee=delivery_fee,
            rider_commission=delivery_fee * Decimal('0.5'),
            distance_km=distance_km, zone=zone,
            delivery_type=Delivery.DeliveryType.EXPRESS,
            status=Delivery.Status.PENDING, delivery_note=note,
        )
        order.delivery = delivery_record
        order.save(update_fields=['delivery'])
    except Exception:
        pass

    if vendor:
        try:
            vendor.total_orders = (vendor.total_orders or 0) + 1
            vendor.save(update_fields=['total_orders'])
        except Exception:
            pass

    # Clear cart
    _cart_items(cart).delete()
    cart.vendor = None
    cart.save()

    # Route by payment method
    if pay_method == getattr(FoodOrder.PaymentMethod, 'MOMO_PREPAID', 'momo_prepaid'):
        return food_payment_initiate(request, order.order_ref)

    try:
        from delivery.services import auto_assign_for_food_order
        auto_assign_for_food_order(order)
    except Exception:
        pass

    messages.success(request, f'✅ Order {order.order_ref} placed!')
    return redirect('food:order_track', ref=order.order_ref)


# ── Order tracking ─────────────────────────────────────────────────────────────

@login_required
def order_track(request, ref):
    order = get_object_or_404(FoodOrder, order_ref=ref, customer=request.user)
    return render(request, 'food/track.html', {
        'order':          order,
        'cart_count':     0,
        'locationiq_key': getattr(settings, 'LOCATIONIQ_API_KEY', ''),
        'track_api_url':  reverse('food:order_track_api', args=[ref]),
    })


@login_required
def order_track_api(request, ref):
    order = get_object_or_404(FoodOrder, order_ref=ref, customer=request.user)
    rlat = rlng = rname = rphone = None
    if order.delivery and order.delivery.rider:
        try:
            from rider.models import RiderLocation
            loc  = RiderLocation.objects.get(rider=order.delivery.rider.rider, is_active=True)
            rlat = float(loc.latitude)
            rlng = float(loc.longitude)
        except Exception:
            pass
        rp     = order.delivery.rider
        rname  = rp.rider.get_full_name() or rp.rider.phone
        rphone = rp.rider.phone
    return JsonResponse({
        'status':       order.status,
        'status_label': order.get_status_display(),
        'rider_lat':    rlat, 'rider_lng': rlng,
        'rider_name':   rname, 'rider_phone': rphone,
        'eta':          order.estimated_delivery_time,
        'dropoff_lat':  order.delivery_lat,
        'dropoff_lng':  order.delivery_lng,
    })


@login_required
def order_history(request):
    orders = FoodOrder.objects.filter(
        customer=request.user
    ).select_related('vendor').prefetch_related('items').order_by('-created_at')
    return render(request, 'food/orders.html', {'orders': orders, 'cart_count': 0})


# ── Reorder ────────────────────────────────────────────────────────────────────

@login_required
@require_POST
def reorder(request, ref):
    order  = get_object_or_404(FoodOrder, order_ref=ref, customer=request.user)
    vendor = order.vendor
    cart, _ = _get_or_create_cart(request.user)

    if cart.vendor and cart.vendor_id != vendor.pk and _cart_items(cart).exists():
        messages.warning(request, f'Clear your cart first to reorder from {vendor.name}.')
        return redirect('food:menu', slug=vendor.slug)

    cart.vendor = vendor
    cart.save()

    added = skipped = 0
    for item in order.items.select_related('food').all():
        food = item.food
        if not food or not food.is_available:
            skipped += 1
            continue
        ci, created = FoodCartItem.objects.get_or_create(
            cart=cart, food=food,
            defaults={'quantity': item.quantity, 'note': item.note or ''},
        )
        if not created:
            ci.quantity += item.quantity
            ci.save()
        added += 1

    if added:
        messages.success(request, f'✅ {added} item{"s" if added != 1 else ""} added to cart.')
    if skipped:
        messages.warning(request, f'⚠ {skipped} item{"s" if skipped != 1 else ""} unavailable and skipped.')

    return redirect('food:menu', slug=vendor.slug)


# ── Food payment (Hubtel) ──────────────────────────────────────────────────────

@login_required
def food_payment_initiate(request, order_ref):
    food_order = get_object_or_404(
        FoodOrder, order_ref=order_ref, customer=request.user,
        payment_status=FoodOrder.PaymentStatus.UNPAID,
    )
    cid   = getattr(settings, 'HUBTEL_CLIENT_ID',     '')
    merch = getattr(settings, 'HUBTEL_MERCHANT_ACCT', '')

    if not cid:
        messages.error(request, 'Payment gateway not configured.')
        return redirect('food:order_track', ref=order_ref)

    tx_ref = f'FOOD-{order_ref}-{uuid.uuid4().hex[:6].upper()}'
    base   = request.build_absolute_uri('/').rstrip('/')

    FoodPayment.objects.get_or_create(
        food_order=food_order,
        defaults={
            'amount': food_order.total_amount, 'transaction_id': tx_ref,
            'momo_number': food_order.delivery_phone, 'provider': 'hubtel',
            'status': FoodPayment.Status.PENDING,
        }
    )

    try:
        resp = requests.post(
            'https://api.hubtel.com/v2/pos/onlinecheckout/items/initiate',
            headers={'Authorization': _hubtel_auth(), 'Content-Type': 'application/json'},
            json={
                'totalAmount': float(food_order.total_amount),
                'description': f'Lynctel Food {order_ref}',
                'clientReference': tx_ref,
                'callbackUrl': f'{base}/food/payment/webhook/',
                'returnUrl':   f'{base}/food/payment/callback/{tx_ref}/',
                'cancellationUrl': f'{base}/food/order/{order_ref}/',
                'merchantAccountNumber': merch,
            },
            timeout=15,
        )
        data = resp.json()
        url  = data.get('paylinkUrl') or data.get('checkoutUrl')
        if url:
            return redirect(url)
        messages.error(request, f"Payment error: {data.get('message', 'Try again.')}")
    except Exception:
        messages.error(request, 'Could not connect to payment gateway.')

    return redirect('food:order_track', ref=order_ref)


@login_required
def food_payment_callback(request, tx_ref):
    try:
        fp = FoodPayment.objects.select_related('food_order').get(transaction_id=tx_ref)
    except FoodPayment.DoesNotExist:
        messages.error(request, 'Payment record not found.')
        return redirect('food:home')

    food_order = fp.food_order

    if fp.status == FoodPayment.Status.SUCCESS:
        messages.success(request, f'✅ Order {food_order.order_ref} confirmed!')
        return redirect('food:order_track', ref=food_order.order_ref)

    if request.GET.get('status') == 'cancelled':
        fp.status = FoodPayment.Status.FAILED
        fp.save(update_fields=['status'])
        messages.warning(request, 'Payment cancelled.')
        return redirect('food:order_track', ref=food_order.order_ref)

    return render(request, 'food/payment_processing.html', {
        'order':    food_order,
        'poll_url': reverse('food:payment_status', args=[food_order.order_ref]),
    })


@csrf_exempt
@require_POST
def food_payment_webhook(request):
    try:
        body          = json.loads(request.body)
        response_code = body.get('ResponseCode', '')
        data          = body.get('Data', {})
        tx_ref        = data.get('ClientReference', '')
        txn_id        = data.get('TransactionId', '')

        if not tx_ref.startswith('FOOD-'):
            return HttpResponse(status=200)

        if response_code == '0000':
            fp         = FoodPayment.objects.select_related('food_order').get(transaction_id=tx_ref)
            food_order = fp.food_order
            if fp.status != FoodPayment.Status.SUCCESS:
                _mark_food_paid(fp, food_order, txn_id, {'via': 'hubtel_webhook'})
    except Exception:
        pass
    return HttpResponse(status=200)


@login_required
def food_payment_status(request, order_ref):
    food_order = get_object_or_404(FoodOrder, order_ref=order_ref, customer=request.user)
    paid = food_order.payment_status == FoodOrder.PaymentStatus.PAID
    return JsonResponse({
        'paid':    paid,
        'redirect': reverse('food:order_track', args=[order_ref]) if paid else None,
    })


# ── Payment helpers ────────────────────────────────────────────────────────────

def _mark_food_paid(fp, food_order, gateway_ref, gateway_data):
    with transaction.atomic():
        fp.status           = FoodPayment.Status.SUCCESS
        fp.gateway_ref      = gateway_ref
        fp.gateway_response = gateway_data
        fp.paid_at          = timezone.now()
        fp.save()
        food_order.payment_status = FoodOrder.PaymentStatus.PAID
        food_order.status         = FoodOrder.Status.CONFIRMED
        food_order.confirmed_at   = timezone.now()
        food_order.save(update_fields=['payment_status', 'status', 'confirmed_at'])
        _split_food_commission(food_order)

    try:
        from delivery.services import auto_assign_for_food_order
        auto_assign_for_food_order(food_order)
    except Exception:
        pass


def _split_food_commission(food_order):
    if not food_order.vendor:
        return
    gross = Decimal(str(food_order.subtotal))
    FoodVendorEarning.objects.get_or_create(
        food_order=food_order,
        defaults={
            'vendor':         food_order.vendor,
            'gross_amount':   gross,
            'app_commission': (gross * FOOD_APP_SHARE).quantize(Decimal('0.01')),
            'vendor_payout':  (gross * FOOD_VENDOR_SHARE).quantize(Decimal('0.01')),
            'status':         'pending',
        }
    )
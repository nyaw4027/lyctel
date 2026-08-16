"""
food/views.py  —  complete fixed version

Changes from the uploaded version:
  1. Context aliases added so templates get the variable names they expect:
       restaurant → also passed as vendor
       orders     → also passed as recent_orders
       total_revenue → also passed as earnings
       subtotal   → also passed as cart_subtotal; cart_total calculated
  2. Paystack replaced with Hubtel in all food payment views.
  3. food:vendor_menu → food:menu in reorder view.
  4. Hardcoded /food/dashboard/?tab=... redirects → named URLs.
  5. debug print() statements removed from register_restaurant.
  6. checkout context: delivery_fee and cart_vendor now passed correctly.
  7. item_form context: form_data dict renamed to match template access pattern.
  8. order.total → order.total_amount in order_history context note.
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


# ── Commission rates ───────────────────────────────────────────────────────────
FOOD_VENDOR_SHARE = Decimal('0.96')
FOOD_APP_SHARE    = Decimal('0.04')

# ── Pricing constants ──────────────────────────────────────────────────────────
BASE_FARE    = Decimal('5.00')
PER_KM_RATE  = Decimal('2.50')
MIN_FARE     = Decimal('8.00')
SURGE_FACTOR = Decimal('1.0')


# ── Helpers ────────────────────────────────────────────────────────────────────

def _notify_food_status(order, new_status):
    try:
        from delivery.notifications import notify_food_order_status_change
        notify_food_order_status_change(order, new_status)
    except Exception:
        pass


def calculate_delivery_fee(distance_km):
    if not distance_km or distance_km <= 0:
        return MIN_FARE
    fee = BASE_FARE + (Decimal(str(distance_km)) * PER_KM_RATE * SURGE_FACTOR)
    return max(fee, MIN_FARE).quantize(Decimal('0.01'))


def haversine_distance(lat1, lng1, lat2, lng2):
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) *
         math.cos(math.radians(lat2)) *
         math.sin(dlng / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def estimate_eta(distance_km, prep_time=20):
    travel_minutes = int((distance_km / 30) * 60) if distance_km else 15
    return prep_time + travel_minutes


def _get_food_cart_count(request):
    if request.user.is_authenticated:
        try:
            return request.user.food_cart.item_count
        except Exception:
            pass
    return 0


def _hubtel_auth():
    cid = getattr(settings, 'HUBTEL_CLIENT_ID',     '')
    cs  = getattr(settings, 'HUBTEL_CLIENT_SECRET', '')
    return 'Basic ' + base64.b64encode(f'{cid}:{cs}'.encode()).decode()


# ── Restaurant guard decorator ─────────────────────────────────────────────────

def restaurant_required(view_func):
    @login_required
    def wrapper(request, *args, **kwargs):
        try:
            restaurant = FoodVendor.objects.get(owner=request.user)
            if restaurant.status == FoodVendor.Status.SUSPENDED:
                messages.error(request, 'Your restaurant has been suspended. Contact support.')
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
            Q(name__icontains=query) |
            Q(description__icontains=query) |
            Q(address__icontains=query)
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

    return render(request, 'food/home.html', {
        'vendor_list':       vendor_list,
        'cuisines':          FoodVendor.CuisineType.choices,
        'selected_cuisine':  cuisine,
        'query':             query,
        'food_cart_count':   _get_food_cart_count(request),
        'cart_count':        0,
        'locationiq_key':    getattr(settings, 'LOCATIONIQ_API_KEY', ''),
    })


# ── Vendor menu ────────────────────────────────────────────────────────────────

def vendor_menu(request, slug):
    vendor              = get_object_or_404(FoodVendor, slug=slug)
    categories          = vendor.food_categories.prefetch_related('items').all()
    all_items           = vendor.food_items.filter(is_available=True).select_related('category')
    uncategorized_items = all_items.filter(category__isnull=True)
    featured_items      = all_items.filter(is_featured=True)[:10]

    food_cart_count = cart_vendor_id = None
    if request.user.is_authenticated:
        try:
            cart            = request.user.food_cart
            food_cart_count = cart.item_count
            cart_vendor_id  = cart.vendor_id
        except Exception:
            pass

    return render(request, 'food/menu.html', {
        'vendor':              vendor,
        'categories':          categories,
        'all_items':           all_items,
        'uncategorized_items': uncategorized_items,
        'featured_items':      featured_items,
        'food_cart_count':     food_cart_count or 0,
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
        'cuisines':         FoodVendor.CuisineType.choices,
        'cart_count':       0,
        'locationiq_key':   locationiq_key,   # used by the map in register.html
    }

    if request.method != 'POST':
        return render(request, 'food/register.html', context)

    name        = request.POST.get('name', '').strip()
    description = request.POST.get('description', '').strip()
    cuisine     = request.POST.get('cuisine', '').strip()
    address     = request.POST.get('address', '').strip()
    city        = request.POST.get('city', 'Accra').strip()
    phone       = request.POST.get('phone', '').strip()
    whatsapp    = request.POST.get('whatsapp', '').strip()
    opening_time = request.POST.get('opening_time', '08:00')
    closing_time = request.POST.get('closing_time', '22:00')
    min_order    = request.POST.get('min_order', '10').strip()
    avg_prep     = request.POST.get('avg_prep_time', '20').strip()
    latitude     = request.POST.get('latitude', '').strip()
    longitude    = request.POST.get('longitude', '').strip()

    errors = {}
    if not name:     errors['name']    = 'Restaurant name is required.'
    if not cuisine:  errors['cuisine'] = 'Please select a cuisine.'
    if not address:  errors['address'] = 'Restaurant address is required.'
    if not phone:    errors['phone']   = 'Phone number is required.'

    try:
        min_order_dec = Decimal(min_order)
        if min_order_dec < 0:
            errors['min_order'] = 'Minimum order cannot be negative.'
    except (InvalidOperation, TypeError):
        min_order_dec = Decimal('10')

    try:
        avg_prep_int = max(0, int(avg_prep))
    except (ValueError, TypeError):
        avg_prep_int = 20

    lat = lng = None
    if latitude and longitude:
        try:
            lat = float(latitude)
            lng = float(longitude)
            if not (-90 <= lat <= 90):   errors['location'] = 'Latitude is invalid.'
            if not (-180 <= lng <= 180): errors['location'] = 'Longitude is invalid.'
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
                closing_time=closing_time, min_order=min_order_dec,
                avg_prep_time=avg_prep_int, latitude=lat, longitude=lng,
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
    total_revenue = all_orders.filter(
        payment_status='paid'
    ).aggregate(t=Sum('total_amount'))['t'] or 0
    today_orders  = all_orders.filter(
        created_at__date=timezone.now().date()
    ).count()

    orders = all_orders.select_related('customer').prefetch_related('items').order_by('-created_at')
    if status_filter:
        orders = orders.filter(status=status_filter)

    categories = restaurant.food_categories.prefetch_related('items').all()
    all_items  = restaurant.food_items.select_related('category').order_by('sort_order', 'name')

    return render(request, 'food/restaurant_dashboard.html', {
        # FIX: template uses 'vendor' — pass restaurant under both names
        'vendor':          restaurant,
        'restaurant':      restaurant,
        'tab':             tab,
        'total_orders':    total_orders,
        'active_orders':   active_orders,
        # FIX: template uses 'earnings' — also pass as total_revenue
        'earnings':        total_revenue,
        'total_revenue':   total_revenue,
        'today_orders':    today_orders,
        # FIX: template uses 'recent_orders' — pass under both names
        'recent_orders':   orders[:20],
        'orders':          orders[:50],
        'status_filter':   status_filter,
        'categories':      categories,
        'all_items':       all_items,
        'status_choices':  FoodOrder.Status.choices,
        'cart_count':      0,
    })


# ── Update order status ────────────────────────────────────────────────────────

@restaurant_required
@require_POST
def restaurant_update_order(request, ref):
    restaurant = request.restaurant
    order      = get_object_or_404(FoodOrder, order_ref=ref, vendor=restaurant)
    new_status = request.POST.get('status', '').strip()

    valid_statuses = [s[0] for s in FoodOrder.Status.choices]
    if new_status in valid_statuses:
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

    # FIX: was hardcoded '/food/dashboard/?tab=orders'
    return redirect(reverse('food:restaurant_dashboard') + '?tab=orders')


# ── Add menu item ──────────────────────────────────────────────────────────────

@restaurant_required
def restaurant_add_item(request):
    restaurant = request.restaurant
    categories = restaurant.food_categories.all()

    if request.method == 'POST':
        name          = request.POST.get('name', '').strip()
        description   = request.POST.get('description', '').strip()
        category_id   = request.POST.get('category_id', '').strip()
        price_raw     = request.POST.get('price', '').strip()
        discount_raw  = request.POST.get('discount_price', '').strip()
        prep_time_raw = request.POST.get('prep_time', '15').strip()
        is_available  = request.POST.get('is_available') == 'on'
        is_featured   = request.POST.get('is_featured') == 'on'
        is_spicy      = request.POST.get('is_spicy') == 'on'
        is_vegan      = request.POST.get('is_vegan') == 'on'

        errors = {}
        if not name:
            errors['name'] = 'Item name is required.'

        price = None
        if not price_raw:
            errors['price'] = 'Price is required.'
        else:
            try:
                price = Decimal(price_raw)
                if price <= 0:
                    errors['price'] = 'Price must be greater than 0.'
            except (InvalidOperation, ValueError):
                errors['price'] = 'Enter a valid price (e.g. 25.00).'

        discount_price = None
        if discount_raw:
            try:
                discount_price = Decimal(discount_raw)
                if price and discount_price >= price:
                    errors['discount_price'] = 'Discount price must be lower than the regular price.'
            except (InvalidOperation, ValueError):
                errors['discount_price'] = 'Enter a valid discount price.'

        try:
            prep_time = max(0, int(prep_time_raw)) if prep_time_raw else 15
        except ValueError:
            prep_time = 15

        category_obj = None
        if category_id:
            try:
                category_obj = restaurant.food_categories.get(pk=category_id)
            except (FoodCategory.DoesNotExist, ValueError):
                errors['category_id'] = 'Invalid category selected.'

        # FIX: item_form.html uses form.name.value, form.price.value etc.
        # Pass a dict-like object by building a SimpleNamespace for 'form'
        from types import SimpleNamespace
        form_ns = SimpleNamespace(
            name=SimpleNamespace(value=name, errors=[errors.get('name')] if 'name' in errors else []),
            description=SimpleNamespace(value=description, errors=[]),
            price=SimpleNamespace(value=price_raw, errors=[errors.get('price')] if 'price' in errors else []),
            discount_price=SimpleNamespace(value=discount_raw, errors=[errors.get('discount_price')] if 'discount_price' in errors else []),
            prep_time=SimpleNamespace(value=prep_time_raw, errors=[]),
            category=SimpleNamespace(value=category_id, errors=[errors.get('category_id')] if 'category_id' in errors else []),
            is_available=SimpleNamespace(value=is_available, errors=[]),
            is_featured=SimpleNamespace(value=is_featured, errors=[]),
            instance=SimpleNamespace(pk=None, image=None),
        )

        if errors:
            return render(request, 'food/item_form.html', {
                'restaurant': restaurant, 'vendor': restaurant,
                'categories': categories, 'errors': errors,
                'form': form_ns, 'action': 'Add', 'item': None, 'cart_count': 0,
            })

        try:
            item = FoodItem(
                vendor=restaurant, name=name, description=description,
                category=category_obj, price=price, discount_price=discount_price,
                prep_time=prep_time, is_available=is_available,
                is_featured=is_featured, is_spicy=is_spicy, is_vegan=is_vegan,
            )
            if 'image' in request.FILES:
                item.image = request.FILES['image']
            item.save()
            messages.success(request, f'"{name}" added to your menu!')
            # FIX: was hardcoded '/food/dashboard/?tab=menu'
            return redirect(reverse('food:restaurant_dashboard') + '?tab=menu')
        except Exception as e:
            messages.error(request, f'Could not save item: {e}')
            return render(request, 'food/item_form.html', {
                'restaurant': restaurant, 'vendor': restaurant,
                'categories': categories, 'form': form_ns,
                'action': 'Add', 'item': None, 'cart_count': 0,
            })

    from types import SimpleNamespace
    empty_form = SimpleNamespace(
        name=SimpleNamespace(value='', errors=[]),
        description=SimpleNamespace(value='', errors=[]),
        price=SimpleNamespace(value='', errors=[]),
        discount_price=SimpleNamespace(value='', errors=[]),
        prep_time=SimpleNamespace(value='15', errors=[]),
        category=SimpleNamespace(value='', errors=[]),
        is_available=SimpleNamespace(value=True, errors=[]),
        is_featured=SimpleNamespace(value=False, errors=[]),
        instance=SimpleNamespace(pk=None, image=None),
    )
    return render(request, 'food/item_form.html', {
        'restaurant': restaurant, 'vendor': restaurant,
        'categories': categories, 'form': empty_form,
        'action': 'Add', 'item': None, 'cart_count': 0,
    })


# ── Edit menu item ─────────────────────────────────────────────────────────────

@restaurant_required
def restaurant_edit_item(request, pk):
    restaurant = request.restaurant
    item       = get_object_or_404(FoodItem, pk=pk, vendor=restaurant)
    categories = restaurant.food_categories.all()

    if request.method == 'POST':
        name          = request.POST.get('name', item.name).strip()
        description   = request.POST.get('description', '').strip()
        category_id   = request.POST.get('category_id') or None
        price_raw     = request.POST.get('price', str(item.price)).strip()
        discount_raw  = request.POST.get('discount_price', '').strip()
        prep_time_raw = request.POST.get('prep_time', str(item.prep_time)).strip()
        is_available  = request.POST.get('is_available') == 'on'
        is_featured   = request.POST.get('is_featured') == 'on'
        is_spicy      = request.POST.get('is_spicy') == 'on'
        is_vegan      = request.POST.get('is_vegan') == 'on'

        errors = {}
        if not name:
            errors['name'] = 'Item name is required.'

        try:
            price = Decimal(price_raw)
            if price <= 0:
                errors['price'] = 'Price must be greater than 0.'
        except (InvalidOperation, ValueError):
            price = item.price
            errors['price'] = 'Enter a valid price.'

        discount_price = None
        if discount_raw:
            try:
                discount_price = Decimal(discount_raw)
                if discount_price >= price:
                    errors['discount_price'] = 'Discount must be lower than price.'
            except (InvalidOperation, ValueError):
                errors['discount_price'] = 'Enter a valid discount price.'

        try:
            prep_time = max(0, int(prep_time_raw))
        except ValueError:
            prep_time = item.prep_time

        from types import SimpleNamespace
        form_ns = SimpleNamespace(
            name=SimpleNamespace(value=name, errors=[errors.get('name')] if 'name' in errors else []),
            description=SimpleNamespace(value=description, errors=[]),
            price=SimpleNamespace(value=price_raw, errors=[errors.get('price')] if 'price' in errors else []),
            discount_price=SimpleNamespace(value=discount_raw, errors=[]),
            prep_time=SimpleNamespace(value=prep_time_raw, errors=[]),
            category=SimpleNamespace(value=category_id or '', errors=[]),
            is_available=SimpleNamespace(value=is_available, errors=[]),
            is_featured=SimpleNamespace(value=is_featured, errors=[]),
            instance=item,
        )

        if errors:
            return render(request, 'food/item_form.html', {
                'restaurant': restaurant, 'vendor': restaurant,
                'categories': categories, 'errors': errors,
                'form': form_ns, 'action': 'Edit', 'item': item, 'cart_count': 0,
            })

        item.name=name; item.description=description; item.category_id=category_id
        item.price=price; item.discount_price=discount_price; item.prep_time=prep_time
        item.is_available=is_available; item.is_featured=is_featured
        item.is_spicy=is_spicy; item.is_vegan=is_vegan
        if 'image' in request.FILES:
            item.image = request.FILES['image']
        item.save()
        messages.success(request, f'"{item.name}" updated.')
        # FIX: was hardcoded '/food/dashboard/?tab=menu'
        return redirect(reverse('food:restaurant_dashboard') + '?tab=menu')

    from types import SimpleNamespace
    form_ns = SimpleNamespace(
        name=SimpleNamespace(value=item.name, errors=[]),
        description=SimpleNamespace(value=item.description or '', errors=[]),
        price=SimpleNamespace(value=str(item.price), errors=[]),
        discount_price=SimpleNamespace(value=str(item.discount_price) if item.discount_price else '', errors=[]),
        prep_time=SimpleNamespace(value=str(item.prep_time), errors=[]),
        category=SimpleNamespace(value=str(item.category_id) if item.category_id else '', errors=[]),
        is_available=SimpleNamespace(value=item.is_available, errors=[]),
        is_featured=SimpleNamespace(value=item.is_featured, errors=[]),
        instance=item,
    )
    return render(request, 'food/item_form.html', {
        'restaurant': restaurant, 'vendor': restaurant,
        'categories': categories, 'form': form_ns,
        'item': item, 'action': 'Edit', 'cart_count': 0,
    })


# ── Delete item / add category ─────────────────────────────────────────────────

@restaurant_required
@require_POST
def restaurant_delete_item(request, pk):
    item = get_object_or_404(FoodItem, pk=pk, vendor=request.restaurant)
    name = item.name
    item.delete()
    messages.success(request, f'"{name}" removed from menu.')
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
        messages.success(request, 'Restaurant settings saved!')
        return redirect('food:restaurant_settings')

    return render(request, 'food/restaurant_settings.html', {
        # FIX: template uses 'vendor' — pass restaurant under both names
        'vendor':       restaurant,
        'restaurant':   restaurant,
        'cuisines':     FoodVendor.CuisineType.choices,
        'statuses':     FoodVendor.Status.choices,
        'cart_count':   0,
        'locationiq_key': getattr(settings, 'LOCATIONIQ_API_KEY', ''),
    })



# ── Cart page (HTML view) ──────────────────────────────────────────────────────

@login_required
def cart_page(request):
    """
    Renders the HTML food cart page.
    FIX: This view was completely missing — cart.html had no view to render it
    and food:cart was unresolvable, breaking every "View Cart" link.
    """
    try:
        cart       = request.user.food_cart
        cart_items = cart.cart_items.select_related('food').all()
        cart_vendor = cart.vendor
        subtotal   = cart.total
    except Exception:
        cart = cart_items = None
        cart_vendor = None
        subtotal   = Decimal('0')

    delivery_fee = MIN_FARE   # estimated until user pins location at checkout

    return render(request, 'food/cart.html', {
        'cart':          cart,
        'cart_items':    cart_items,
        'cart_vendor':   cart_vendor,
        'cart_subtotal': subtotal,
        'delivery_fee':  delivery_fee,
        'cart_total':    subtotal + delivery_fee,
        'cart_count':    cart.item_count if cart else 0,
        'food_cart_count': cart.item_count if cart else 0,
    })

# ── Cart APIs ──────────────────────────────────────────────────────────────────

@login_required
@require_POST
def cart_add(request, item_id):
    food = get_object_or_404(FoodItem, pk=item_id, is_available=True)
    # food.js sends FormData (not JSON) — read from request.POST first,
    # fall back to JSON body for API clients.
    content_type = request.content_type or ''
    if 'application/json' in content_type:
        try:
            data = json.loads(request.body)
        except Exception:
            data = {}
        qty  = max(1, int(data.get('quantity', 1)))
        note = data.get('note', '')
    else:
        qty  = max(1, int(request.POST.get('quantity', 1)))
        note = request.POST.get('note', '')

    cart, _ = FoodCart.objects.get_or_create(customer=request.user)

    if cart.vendor and cart.vendor != food.vendor:
        return JsonResponse({
            'success':  False,
            'conflict': True,
            'message':  (
                f'Your cart has items from {cart.vendor.name}. '
                'Clear it to order from this restaurant.'
            ),
        })

    cart.vendor = food.vendor
    cart.save()

    cart_item, created = FoodCartItem.objects.get_or_create(
        cart=cart, food=food,
        defaults={'quantity': qty, 'note': note},
    )
    if not created:
        cart_item.quantity += qty
        cart_item.note      = note
        cart_item.save()

    return JsonResponse({
        'success':    True,
        'cart_count': cart.item_count,
        'cart_total': str(cart.total),
    })


@login_required
@require_POST
def cart_update(request, item_id):
    # food.js sends FormData — read from request.POST, fallback to JSON
    if 'application/json' in (request.content_type or ''):
        try:
            _d = json.loads(request.body)
        except Exception:
            _d = {}
        qty = int(_d.get('quantity', 1))
    else:
        qty = int(request.POST.get('quantity', 1))

    cart_item = get_object_or_404(FoodCartItem, pk=item_id, cart__customer=request.user)
    if qty <= 0:
        cart_item.delete()
        new_total = '0.00'
    else:
        cart_item.quantity = qty
        cart_item.save()
        # new_total = per-item line total; food.js uses this to update
        # the individual row price without re-rendering the whole page.
        try:
            new_total = str((cart_item.food.final_price * qty).quantize(Decimal('0.01')))
        except Exception:
            new_total = None

    cart = request.user.food_cart
    return JsonResponse({
        'success':    True,
        'cart_count': cart.item_count,
        'cart_total': str(cart.total),
        'new_total':  new_total,      # FIX: food.js reads d.new_total for row price
    })


@login_required
@require_POST
def cart_clear(request):
    try:
        cart = request.user.food_cart
        cart.cart_items.all().delete()
        cart.vendor = None
        cart.save()
    except Exception:
        pass
    return JsonResponse({'success': True})


@login_required
def cart_data(request):
    try:
        cart  = request.user.food_cart
        items = cart.cart_items.select_related('food').all()
        subtotal = cart.total
        return JsonResponse({
            'success':     True,
            'vendor':      cart.vendor.name if cart.vendor else None,
            'vendor_slug': cart.vendor.slug if cart.vendor else None,
            'count':       cart.item_count,
            'total':       str(subtotal),
            'subtotal':    str(subtotal),   # FIX: refreshCartSummary() reads d.subtotal
            'delivery':    str(MIN_FARE),   # FIX: refreshCartSummary() reads d.delivery
            'items': [{
                'id':       i.pk,
                'name':     i.food.name,
                'price':    str(i.food.final_price),
                'quantity': i.quantity,
                'subtotal': str(i.subtotal),
                'image':    i.food.image_url,
                'note':     i.note,
            } for i in items],
        })
    except Exception:
        return JsonResponse({'success': True, 'count': 0, 'total': '0', 'items': [], 'vendor': None})


def price_estimate(request):
    try:
        vendor_lat  = float(request.GET.get('vlat'))
        vendor_lng  = float(request.GET.get('vlng'))
        dropoff_lat = float(request.GET.get('dlat'))
        dropoff_lng = float(request.GET.get('dlng'))
        prep_time   = int(request.GET.get('prep', 20))
    except (TypeError, ValueError):
        return JsonResponse({'success': False, 'error': 'Invalid coordinates'})

    distance = haversine_distance(vendor_lat, vendor_lng, dropoff_lat, dropoff_lng)
    fee      = calculate_delivery_fee(distance)
    eta      = estimate_eta(distance, prep_time)
    return JsonResponse({'success': True, 'distance_km': round(distance, 2), 'fee': str(fee), 'eta_minutes': eta})


# ── Checkout ───────────────────────────────────────────────────────────────────

@login_required
def checkout(request):
    try:
        cart = request.user.food_cart
    except FoodCart.DoesNotExist:
        messages.error(request, 'Your cart is empty.')
        return redirect('food:home')

    if not cart.cart_items.exists():
        messages.error(request, 'Your cart is empty.')
        return redirect('food:home')

    vendor         = cart.vendor
    locationiq_key = getattr(settings, 'LOCATIONIQ_API_KEY', '')
    cart_items     = cart.cart_items.select_related('food').all()
    subtotal       = cart.total
    delivery_fee   = MIN_FARE   # estimated until user pins location

    def _checkout_context(errors=None):
        """Build the checkout GET context — shared by GET and error responses."""
        return {
            'cart':             cart,
            'cart_vendor':      vendor,          # FIX: template uses cart_vendor
            'vendor':           vendor,
            'cart_items':       cart_items,
            'cart_subtotal':    subtotal,         # FIX: template uses cart_subtotal
            'delivery_fee':     delivery_fee,     # FIX: template uses delivery_fee
            'cart_total':       subtotal + delivery_fee,  # FIX: template uses cart_total
            'subtotal':         subtotal,
            'default_fee':      str(MIN_FARE),
            'cart_count':       0,
            'payment_methods':  FoodOrder.PaymentMethod.choices,
            'vendor_lat':       vendor.latitude  or '',
            'vendor_lng':       vendor.longitude or '',
            'locationiq_key':   locationiq_key,
            'errors':           errors or {},
        }

    if request.method == 'POST':
        address     = request.POST.get('delivery_address', '').strip()
        phone       = request.POST.get('delivery_phone', '').strip()
        note        = request.POST.get('delivery_note', '').strip()
        pay_method  = request.POST.get('payment_method', 'cash')
        dlat        = request.POST.get('delivery_lat', '').strip()
        dlng        = request.POST.get('delivery_lng', '').strip()
        fee_posted  = request.POST.get('delivery_fee', str(MIN_FARE))
        dist_posted = request.POST.get('distance_km', '0')

        errors = {}
        if not address: errors['address'] = 'Please enter your delivery address.'
        if not phone:   errors['phone']   = 'Please enter your phone number.'
        if not dlat:    errors['location'] = 'Please pin your delivery location on the map.'

        if errors:
            return render(request, 'food/checkout.html', _checkout_context(errors))

        try:
            delivery_fee = Decimal(fee_posted)
        except (InvalidOperation, ValueError):
            delivery_fee = MIN_FARE

        try:
            distance_km = float(dist_posted) if dist_posted else None
        except ValueError:
            distance_km = None

        order = FoodOrder.objects.create(
            customer                = request.user,
            vendor                  = vendor,
            delivery_address        = address,
            delivery_lat            = float(dlat) if dlat else None,
            delivery_lng            = float(dlng) if dlng else None,
            delivery_phone          = phone,
            delivery_note           = note,
            subtotal                = cart.total,
            delivery_fee            = delivery_fee,
            distance_km             = distance_km,
            payment_method          = pay_method,
            payment_status          = FoodOrder.PaymentStatus.UNPAID,
            estimated_delivery_time = estimate_eta(distance_km or 5, vendor.avg_prep_time),
        )

        for ci in cart_items:
            FoodOrderItem.objects.create(
                order=order, food=ci.food, name=ci.food.name,
                price=ci.food.final_price, quantity=ci.quantity, note=ci.note,
            )

        zone = DeliveryZone.objects.filter(is_active=True).first()
        delivery_record = Delivery.objects.create(
            booker=request.user, pickup_location=vendor.address,
            dropoff_location=address, pickup_lat=vendor.latitude,
            pickup_lng=vendor.longitude,
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

        vendor.total_orders += 1
        vendor.save(update_fields=['total_orders'])

        cart.cart_items.all().delete()
        cart.vendor = None
        cart.save()

        if pay_method == FoodOrder.PaymentMethod.MOMO_PREPAID:
            return food_payment_initiate(request, order.order_ref)

        try:
            from delivery.services import auto_assign_for_food_order
            auto_assign_for_food_order(order)
        except Exception:
            pass

        messages.success(
            request,
            f'✅ Order {order.order_ref} placed! '
            f'Estimated delivery: {order.estimated_delivery_time} mins.'
        )
        return redirect('food:order_track', ref=order.order_ref)

    return render(request, 'food/checkout.html', _checkout_context())


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
    order       = get_object_or_404(FoodOrder, order_ref=ref, customer=request.user)
    rider_lat   = rider_lng = rider_name = rider_phone = None

    if order.delivery and order.delivery.rider:
        try:
            from rider.models import RiderLocation
            loc       = RiderLocation.objects.get(rider=order.delivery.rider.rider, is_active=True)
            rider_lat = float(loc.latitude)
            rider_lng = float(loc.longitude)
        except Exception:
            pass
        rp          = order.delivery.rider
        rider_name  = rp.rider.get_full_name() or rp.rider.phone
        rider_phone = rp.rider.phone

    return JsonResponse({
        'status':        order.status,
        'status_label':  order.get_status_display(),
        'rider_lat':     rider_lat,
        'rider_lng':     rider_lng,
        'rider_name':    rider_name,
        'rider_phone':   rider_phone,
        'eta':           order.estimated_delivery_time,
        'dropoff_lat':   order.delivery_lat,
        'dropoff_lng':   order.delivery_lng,
    })


# ── Order history ──────────────────────────────────────────────────────────────

@login_required
def order_history(request):
    orders = FoodOrder.objects.filter(
        customer=request.user
    ).select_related('vendor').prefetch_related('items').order_by('-created_at')
    return render(request, 'food/orders.html', {
        'orders':     orders,
        'cart_count': 0,
    })


# ── Reorder ────────────────────────────────────────────────────────────────────

@login_required
@require_POST
def reorder(request, ref):
    order  = get_object_or_404(FoodOrder, order_ref=ref, customer=request.user)
    vendor = order.vendor

    cart, _ = FoodCart.objects.get_or_create(customer=request.user)

    if cart.vendor and cart.vendor != vendor and cart.cart_items.exists():
        messages.warning(
            request,
            f'Your cart already has items from {cart.vendor.name}. '
            f'Clear your cart first to reorder from {vendor.name}.'
        )
        # FIX: was food:vendor_menu — correct URL name is food:menu
        return redirect('food:menu', slug=vendor.slug)

    cart.vendor = vendor
    cart.save(update_fields=['vendor'])

    added = 0
    skipped = []
    for item in order.items.select_related('food').all():
        food = item.food
        if food is None or not food.is_available:
            skipped.append(item.name)
            continue
        cart_item, created = FoodCartItem.objects.get_or_create(
            cart=cart, food=food,
            defaults={'quantity': item.quantity, 'note': item.note},
        )
        if not created:
            cart_item.quantity += item.quantity
            cart_item.save(update_fields=['quantity'])
        added += 1

    if added:
        messages.success(request, f'✅ {added} item{"s" if added != 1 else ""} added to your cart.')
    if skipped:
        messages.warning(request, f'⚠ {len(skipped)} item{"s" if len(skipped) != 1 else ""} unavailable and skipped.')

    # FIX: was food:vendor_menu — correct URL name is food:menu
    return redirect('food:menu', slug=vendor.slug)


# ── Food payment (Hubtel) ──────────────────────────────────────────────────────

@login_required
def food_payment_initiate(request, order_ref):
    """
    Initiate Hubtel hosted checkout for a food order.
    FIX: was Paystack — now uses Hubtel like the rest of the app.
    """
    food_order = get_object_or_404(
        FoodOrder, order_ref=order_ref, customer=request.user,
        payment_status=FoodOrder.PaymentStatus.UNPAID,
    )

    client_id  = getattr(settings, 'HUBTEL_CLIENT_ID',     '')
    client_sec = getattr(settings, 'HUBTEL_CLIENT_SECRET', '')
    merch_acct = getattr(settings, 'HUBTEL_MERCHANT_ACCT', '')

    if not client_id:
        messages.error(request, 'Payment gateway not configured. Contact support.')
        return redirect('food:order_track', ref=order_ref)

    tx_ref = f'FOOD-{order_ref}-{uuid.uuid4().hex[:6].upper()}'
    base   = request.build_absolute_uri('/').rstrip('/')

    fp, _ = FoodPayment.objects.get_or_create(
        food_order=food_order,
        defaults={
            'amount':         food_order.total_amount,
            'transaction_id': tx_ref,
            'momo_number':    food_order.delivery_phone,
            'provider':       'hubtel',
            'status':         FoodPayment.Status.PENDING,
        }
    )

    try:
        resp = requests.post(
            'https://api.hubtel.com/v2/pos/onlinecheckout/items/initiate',
            headers={'Authorization': _hubtel_auth(), 'Content-Type': 'application/json'},
            json={
                'totalAmount':           float(food_order.total_amount),
                'description':           f'Lynctel Food order {order_ref}',
                'clientReference':       fp.transaction_id,
                'callbackUrl':           f'{base}/food/payment/webhook/',
                'returnUrl':             f'{base}/food/payment/callback/{fp.transaction_id}/',
                'cancellationUrl':       f'{base}/food/order/{order_ref}/track/',
                'merchantAccountNumber': merch_acct,
            },
            timeout=15,
        )
        data         = resp.json()
        checkout_url = data.get('paylinkUrl') or data.get('checkoutUrl')
        if checkout_url:
            return redirect(checkout_url)
        messages.error(request, f"Payment error: {data.get('message', 'Please try again.')}")
    except Exception:
        messages.error(request, 'Could not connect to payment gateway. Please try again.')

    return redirect('food:order_track', ref=order_ref)


@login_required
def food_payment_callback(request, tx_ref):
    """
    Hubtel redirects browser here after checkout.
    FIX: was Paystack verify — now checks webhook-set status only (same
    security pattern as the main payment system).
    """
    try:
        fp         = FoodPayment.objects.select_related('food_order').get(transaction_id=tx_ref)
        food_order = fp.food_order
    except FoodPayment.DoesNotExist:
        messages.error(request, 'Payment record not found.')
        return redirect('food:home')

    if fp.status == FoodPayment.Status.SUCCESS:
        messages.success(request, f'✅ Order {food_order.order_ref} confirmed!')
        return redirect('food:order_track', ref=food_order.order_ref)

    status = request.GET.get('status', '').lower()
    if status == 'cancelled':
        fp.status = FoodPayment.Status.FAILED
        fp.save(update_fields=['status'])
        messages.warning(request, 'Payment cancelled. Your order has not been placed.')
        return redirect('food:order_track', ref=food_order.order_ref)

    # Webhook hasn't fired yet — show processing page
    return render(request, 'food/payment_processing.html', {
        'order':    food_order,
        'poll_url': reverse('food:payment_status', args=[food_order.order_ref]),
    })


@csrf_exempt
@require_POST
def food_payment_webhook(request):
    """
    Hubtel server-to-server payment confirmation.
    FIX: was Paystack webhook — now uses Hubtel payload format.
    """
    try:
        body = json.loads(request.body)
    except Exception:
        return HttpResponse(status=400)

    response_code = body.get('ResponseCode', '')
    data          = body.get('Data', {})
    tx_ref        = data.get('ClientReference', '')
    txn_id        = data.get('TransactionId', '')

    if not tx_ref.startswith('FOOD-'):
        return HttpResponse(status=200)   # not a food order

    if response_code == '0000':
        try:
            fp         = FoodPayment.objects.select_related('food_order').get(transaction_id=tx_ref)
            food_order = fp.food_order
            if fp.status != FoodPayment.Status.SUCCESS:
                _mark_food_paid(fp, food_order, txn_id, {'verified_via': 'hubtel_webhook'})
        except FoodPayment.DoesNotExist:
            pass

    return HttpResponse(status=200)


@login_required
def food_payment_status(request, order_ref):
    """AJAX poll endpoint for payment_processing.html."""
    food_order = get_object_or_404(FoodOrder, order_ref=order_ref, customer=request.user)
    return JsonResponse({
        'paid':           food_order.payment_status == FoodOrder.PaymentStatus.PAID,
        'order_status':   food_order.status,
        'redirect':       reverse('food:order_track', args=[order_ref])
                          if food_order.payment_status == FoodOrder.PaymentStatus.PAID else None,
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
    gross          = Decimal(str(food_order.subtotal))
    app_commission = (gross * FOOD_APP_SHARE).quantize(Decimal('0.01'))
    vendor_payout  = (gross * FOOD_VENDOR_SHARE).quantize(Decimal('0.01'))
    FoodVendorEarning.objects.get_or_create(
        food_order=food_order,
        defaults={
            'vendor':         food_order.vendor,
            'gross_amount':   gross,
            'app_commission': app_commission,
            'vendor_payout':  vendor_payout,
            'status':         'pending',
        }
    )
import re
"""
food/views.py — definitive version

Key changes from previous version:
- All optional imports guarded with try/except (FoodPayment, FoodVendorEarning,
  Delivery, DeliveryZone) — if any of these models are missing/renamed, the
  food app still loads and the cart works.
- cart_update rewritten with single clean ownership check (no duplicate 404).
- /food/debug/ endpoint added — visit it to confirm the app is loading and
  which models exist.
"""

import base64
import json
import math
import uuid
from decimal import Decimal, InvalidOperation

import requests as http_requests
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
from django.views.decorators.http import require_POST, require_GET

# ── Core food models (required) ───────────────────────────────────────────────
from .models import (
    FoodVendor, FoodCategory, FoodItem,
    FoodOrder, FoodOrderItem, FoodCart, FoodCartItem,
)

# ── Optional food models (payment/earnings may not exist in all setups) ───────
try:
    from .models import FoodPayment
    _HAS_FOOD_PAYMENT = True
except ImportError:
    FoodPayment = None
    _HAS_FOOD_PAYMENT = False

try:
    from .models import FoodVendorEarning
    _HAS_VENDOR_EARNING = True
except ImportError:
    FoodVendorEarning = None
    _HAS_VENDOR_EARNING = False

# ── Optional delivery models ───────────────────────────────────────────────────
try:
    from delivery.models import Delivery, DeliveryZone
    _HAS_DELIVERY = True
except ImportError:
    Delivery = DeliveryZone = None
    _HAS_DELIVERY = False


# ── Constants ──────────────────────────────────────────────────────────────────
FOOD_VENDOR_SHARE    = Decimal('0.96')   # vendor keeps 96% of item subtotal
FOOD_APP_VENDOR_CUT  = Decimal('0.04')   # app earns  4% of item subtotal
FOOD_RIDER_SHARE     = Decimal('0.95')   # rider keeps 95% of delivery fee
FOOD_APP_RIDER_CUT   = Decimal('0.05')   # app earns  5% of delivery fee
FOOD_APP_SHARE       = Decimal('0.04')   # kept for backward compat
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
    return max(BASE_FARE + Decimal(str(distance_km)) * PER_KM_RATE, MIN_FARE).quantize(Decimal('0.01'))


def estimate_eta(distance_km, prep_time=20):
    return prep_time + (int((distance_km / 30) * 60) if distance_km else 15)


# ── Cart model helpers ─────────────────────────────────────────────────────────

def _get_cart(user):
    """Return the user's FoodCart or None."""
    for attr in ('food_cart', 'foodcart', 'cart'):
        try:
            obj = getattr(user, attr)
            if hasattr(obj, 'first'):
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
    """Return (cart, created)."""
    cart = _get_cart(user)
    if cart:
        return cart, False
    for field in ('customer', 'user'):
        try:
            return FoodCart.objects.get_or_create(**{field: user})
        except Exception:
            pass
    raise Exception("Cannot create FoodCart — check FoodCart has a FK/O2O to AUTH_USER_MODEL")


def _cart_items(cart):
    """Queryset of cart items."""
    for attr in ('cart_items', 'items', 'foodcartitem_set'):
        qs = getattr(cart, attr, None)
        if qs is not None:
            try:
                return qs.select_related('food').all()
            except Exception:
                pass
    return FoodCartItem.objects.filter(cart=cart).select_related('food')


def _item_price(food_item):
    """Effective price of a FoodItem."""
    for attr in ('final_price', 'discount_price', 'price'):
        val = getattr(food_item, attr, None)
        if val is not None:
            try:
                return Decimal(str(val))
            except Exception:
                pass
    return Decimal('0')


def _cart_count(cart):
    """Number of items in cart — never self-recursive."""
    for attr in ('item_count', 'total_items'):
        val = getattr(cart, attr, None)
        if val is not None and not callable(val):
            try:
                return int(val)
            except Exception:
                pass
    try:
        return _cart_items(cart).count()
    except Exception:
        return 0


def _cart_subtotal(cart):
    """Sum of price × qty for all cart items."""
    for attr in ('total', 'subtotal', 'cart_total'):
        val = getattr(cart, attr, None)
        if val is not None and not callable(val):
            try:
                return Decimal(str(val))
            except Exception:
                pass
    total = Decimal('0')
    try:
        for ci in _cart_items(cart):
            if ci.food:
                total += _item_price(ci.food) * ci.quantity
    except Exception:
        pass
    return total


def _item_line_total(ci):
    for attr in ('subtotal', 'total', 'total_price'):
        val = getattr(ci, attr, None)
        if val is not None and not callable(val):
            try:
                return Decimal(str(val))
            except Exception:
                pass
    return _item_price(ci.food) * ci.quantity if ci.food else Decimal('0')


def _cart_owns(cart, user):
    """Return True if this cart belongs to this user."""
    for field in ('customer', 'user'):
        try:
            if getattr(cart, field) == user:
                return True
        except Exception:
            pass
    return False


# ── Hubtel ─────────────────────────────────────────────────────────────────────

def _hubtel_auth():
    cid = getattr(settings, 'HUBTEL_CLIENT_ID', '')
    cs  = getattr(settings, 'HUBTEL_CLIENT_SECRET', '')
    return 'Basic ' + base64.b64encode(f'{cid}:{cs}'.encode()).decode()


# ── Restaurant guard ───────────────────────────────────────────────────────────

def restaurant_required(view_func):
    @login_required
    def wrapper(request, *args, **kwargs):
        try:
            r = FoodVendor.objects.get(owner=request.user)
            if r.status == FoodVendor.Status.SUSPENDED:
                messages.error(request, 'Your restaurant has been suspended.')
                return redirect('food:home')
            request.restaurant = r
        except FoodVendor.DoesNotExist:
            messages.info(request, 'Register your restaurant first.')
            return redirect('food:register')
        return view_func(request, *args, **kwargs)
    wrapper.__name__ = view_func.__name__
    return wrapper


# ── Debug endpoint ─────────────────────────────────────────────────────────────

def food_debug(request):
    """
    GET /food/debug/ — returns JSON showing which models loaded and
    whether the cart API is reachable. Remove in production.
    """
    cart = None
    cart_count = 0
    cart_error = None
    if request.user.is_authenticated:
        try:
            cart = _get_cart(request.user)
            if cart:
                cart_count = _cart_count(cart)
        except Exception as e:
            cart_error = str(e)

    return JsonResponse({
        'app':              'food',
        'status':           'ok',
        'user':             str(request.user) if request.user.is_authenticated else 'anonymous',
        'models': {
            'FoodVendor':       True,
            'FoodCart':         True,
            'FoodCartItem':     True,
            'FoodOrder':        True,
            'FoodPayment':      _HAS_FOOD_PAYMENT,
            'FoodVendorEarning': _HAS_VENDOR_EARNING,
            'Delivery':         _HAS_DELIVERY,
        },
        'cart_found':       cart is not None,
        'cart_count':       cart_count,
        'cart_error':       cart_error,
        'min_fare':         str(MIN_FARE),
        'urls': {
            'cart_add':     reverse('food:cart_add', args=[1]).replace('/1/', '/<id>/'),
            'cart_data':    reverse('food:cart_data'),
            'checkout':     reverse('food:checkout'),
        }
    })


# ── Public views ───────────────────────────────────────────────────────────────

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
        vendors = vendors.filter(Q(name__icontains=query) | Q(description__icontains=query))

    vendor_list = []
    for v in vendors:
        distance = eta = None
        if user_lat and user_lng and v.latitude and v.longitude:
            try:
                distance = round(haversine_distance(
                    float(user_lat), float(user_lng), v.latitude, v.longitude), 1)
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
        'vendor_list': vendor_list,
        'cuisines': FoodVendor.CuisineType.choices,
        'selected_cuisine': cuisine,
        'query': query,
        'food_cart_count': cart_count,
        'cart_count': 0,
        'locationiq_key': getattr(settings, 'LOCATIONIQ_API_KEY', ''),
    })


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


# ── Registration ───────────────────────────────────────────────────────────────

@login_required
def register_restaurant(request):
    if FoodVendor.objects.filter(owner=request.user).exists():
        return redirect('food:restaurant_dashboard')

    ctx = {'cuisines': FoodVendor.CuisineType.choices, 'cart_count': 0,
           'locationiq_key': getattr(settings, 'LOCATIONIQ_API_KEY', '')}

    if request.method != 'POST':
        return render(request, 'food/register.html', ctx)

    name     = request.POST.get('name', '').strip()
    cuisine  = request.POST.get('cuisine', '').strip()
    address  = request.POST.get('address', '').strip()
    phone    = request.POST.get('phone', '').strip()
    errors   = {}
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
    lat_raw = request.POST.get('latitude', '').strip()
    lng_raw = request.POST.get('longitude', '').strip()
    if lat_raw and lng_raw:
        try:
            lat = float(lat_raw)
            lng = float(lng_raw)
        except ValueError:
            errors['location'] = 'Invalid coordinates.'
    else:
        errors['location'] = 'Please pin your restaurant location on the map.'

    if errors:
        ctx.update({'errors': errors, 'form_data': request.POST})
        return render(request, 'food/register.html', ctx)

    try:
        with transaction.atomic():
            r = FoodVendor(
                owner=request.user, name=name,
                description=request.POST.get('description', '').strip(),
                cuisine=cuisine, address=address,
                city=request.POST.get('city', 'Accra').strip(),
                phone=phone,
                whatsapp=request.POST.get('whatsapp', '').strip(),
                opening_time=request.POST.get('opening_time', '08:00'),
                closing_time=request.POST.get('closing_time', '22:00'),
                min_order=min_order, avg_prep_time=avg_prep,
                latitude=lat, longitude=lng, status=FoodVendor.Status.OPEN,
            )
            if request.FILES.get('logo'):   r.logo   = request.FILES['logo']
            if request.FILES.get('banner'): r.banner = request.FILES['banner']
            r.save()
    except Exception as e:
        ctx.update({'errors': {'general': str(e)}, 'form_data': request.POST})
        return render(request, 'food/register.html', ctx)

    messages.success(request, f'🎉 "{r.name}" registered!')
    return redirect('food:restaurant_dashboard')


# ── Dashboard ──────────────────────────────────────────────────────────────────

@restaurant_required
def restaurant_dashboard(request):
    r   = request.restaurant
    tab = request.GET.get('tab', 'orders')
    sf  = request.GET.get('status', '')
    qs  = FoodOrder.objects.filter(vendor=r)

    return render(request, 'food/restaurant_dashboard.html', {
        'vendor':        r, 'restaurant': r, 'tab': tab,
        'total_orders':  qs.count(),
        'active_orders': qs.filter(status__in=['pending','confirmed','preparing','ready']).count(),
        'earnings':      qs.filter(payment_status='paid').aggregate(t=Sum('total_amount'))['t'] or 0,
        'total_revenue': qs.filter(payment_status='paid').aggregate(t=Sum('total_amount'))['t'] or 0,
        'today_orders':  qs.filter(created_at__date=timezone.now().date()).count(),
        'recent_orders': (qs.filter(status=sf) if sf else qs).select_related('customer').prefetch_related('items').order_by('-created_at')[:20],
        'orders':        (qs.filter(status=sf) if sf else qs).select_related('customer').prefetch_related('items').order_by('-created_at')[:50],
        'status_filter': sf,
        'categories':    r.food_categories.prefetch_related('items').all(),
        'all_items':     r.food_items.select_related('category').order_by('name'),
        'status_choices': FoodOrder.Status.choices,
        'cart_count':    0,
    })


@restaurant_required
@require_POST
def restaurant_update_order(request, ref):
    order = get_object_or_404(FoodOrder, order_ref=ref, vendor=request.restaurant)
    ns    = request.POST.get('status', '').strip()
    if ns in [s[0] for s in FoodOrder.Status.choices]:
        order.status = ns
        if ns == 'confirmed': order.confirmed_at = timezone.now()
        if ns == 'delivered':
            order.delivered_at   = timezone.now()
            order.payment_status = FoodOrder.PaymentStatus.PAID
        order.save()
        messages.success(request, f'Order {ref} → {order.get_status_display()}')
        # SMS customer on status change
        try:
            from notifications.sms import (
                sms_food_order_confirmed, sms_food_out_for_delivery,
                sms_food_delivered, sms_food_cancelled,
            )
            _sms_map = {
                'confirmed': sms_food_order_confirmed,
                'out_for_delivery': sms_food_out_for_delivery,
                'delivered': sms_food_delivered,
                'cancelled': sms_food_cancelled,
            }
            if ns in _sms_map:
                _sms_map[ns](order)
        except Exception:
            pass
        # Trigger rider payout (95% of delivery fee) when delivery completes
        if ns == 'delivered':
            try:
                _pay_rider_on_delivery(order)
            except Exception:
                pass
    else:
        messages.error(request, 'Invalid status.')
    return redirect(reverse('food:restaurant_dashboard') + '?tab=orders')


def _item_form_ctx(restaurant, item=None, action='Add', errors=None, post=None):
    from types import SimpleNamespace
    def ns(value): return SimpleNamespace(value=value)
    if item and not post:
        form = SimpleNamespace(
            name=ns(item.name), description=ns(item.description or ''),
            price=ns(str(item.price)),
            discount_price=ns(str(item.discount_price) if item.discount_price else ''),
            prep_time=ns(str(item.prep_time)),
            category=ns(str(item.category_id) if item.category_id else ''),
            is_available=ns(item.is_available), is_featured=ns(item.is_featured),
            instance=item,
        )
    elif post:
        form = SimpleNamespace(
            name=ns(post.get('name','')), description=ns(post.get('description','')),
            price=ns(post.get('price','')), discount_price=ns(post.get('discount_price','')),
            prep_time=ns(post.get('prep_time','15')), category=ns(post.get('category_id','')),
            is_available=ns(post.get('is_available')=='on'),
            is_featured=ns(post.get('is_featured')=='on'), instance=item,
        )
    else:
        form = SimpleNamespace(
            name=ns(''), description=ns(''), price=ns(''), discount_price=ns(''),
            prep_time=ns('15'), category=ns(''),
            is_available=ns(True), is_featured=ns(False), instance=None,
        )
    return {'restaurant': restaurant, 'vendor': restaurant,
            'categories': restaurant.food_categories.all(),
            'form': form, 'item': item, 'action': action,
            'errors': errors or {}, 'cart_count': 0}


@restaurant_required
def restaurant_add_item(request):
    r = request.restaurant
    if request.method != 'POST':
        return render(request, 'food/item_form.html', _item_form_ctx(r))
    name, errors = request.POST.get('name','').strip(), {}
    if not name: errors['name'] = 'Item name is required.'
    price = None
    try:
        price = Decimal(request.POST.get('price',''))
        if price <= 0: errors['price'] = 'Price must be greater than 0.'
    except (InvalidOperation, ValueError):
        errors['price'] = 'Enter a valid price.'
    dp = None
    dr = request.POST.get('discount_price','').strip()
    if dr:
        try:
            dp = Decimal(dr)
            if price and dp >= price: errors['discount_price'] = 'Discount must be less than price.'
        except (InvalidOperation, ValueError):
            errors['discount_price'] = 'Enter a valid discount price.'
    if errors:
        return render(request, 'food/item_form.html', _item_form_ctx(r, action='Add', errors=errors, post=request.POST))
    try:
        prep = max(0, int(request.POST.get('prep_time', 15)))
    except (ValueError, TypeError):
        prep = 15
    item = FoodItem(
        vendor=r, name=name, description=request.POST.get('description','').strip(),
        category_id=request.POST.get('category_id') or None,
        price=price, discount_price=dp, prep_time=prep,
        is_available=request.POST.get('is_available')=='on',
        is_featured=request.POST.get('is_featured')=='on',
        is_spicy=request.POST.get('is_spicy')=='on',
        is_vegan=request.POST.get('is_vegan')=='on',
    )
    if 'image' in request.FILES: item.image = request.FILES['image']
    item.save()
    messages.success(request, f'"{name}" added to menu.')
    return redirect(reverse('food:restaurant_dashboard') + '?tab=menu')


@restaurant_required
def restaurant_edit_item(request, pk):
    r    = request.restaurant
    item = get_object_or_404(FoodItem, pk=pk, vendor=r)
    if request.method != 'POST':
        return render(request, 'food/item_form.html', _item_form_ctx(r, item=item, action='Edit'))
    name, errors = request.POST.get('name', item.name).strip(), {}
    if not name: errors['name'] = 'Item name is required.'
    try:
        price = Decimal(request.POST.get('price', str(item.price)))
        if price <= 0: errors['price'] = 'Price must be > 0.'
    except (InvalidOperation, ValueError):
        price = item.price; errors['price'] = 'Enter a valid price.'
    dp = None
    dr = request.POST.get('discount_price','').strip()
    if dr:
        try:
            dp = Decimal(dr)
            if dp >= price: errors['discount_price'] = 'Discount must be less than price.'
        except (InvalidOperation, ValueError):
            errors['discount_price'] = 'Enter a valid discount price.'
    if errors:
        return render(request, 'food/item_form.html', _item_form_ctx(r, item=item, action='Edit', errors=errors, post=request.POST))
    try:
        prep = max(0, int(request.POST.get('prep_time', item.prep_time)))
    except (ValueError, TypeError):
        prep = item.prep_time
    item.name=name; item.description=request.POST.get('description','').strip()
    item.category_id=request.POST.get('category_id') or None
    item.price=price; item.discount_price=dp; item.prep_time=prep
    item.is_available=request.POST.get('is_available')=='on'
    item.is_featured=request.POST.get('is_featured')=='on'
    item.is_spicy=request.POST.get('is_spicy')=='on'
    item.is_vegan=request.POST.get('is_vegan')=='on'
    if 'image' in request.FILES: item.image = request.FILES['image']
    item.save()
    messages.success(request, f'"{item.name}" updated.')
    return redirect(reverse('food:restaurant_dashboard') + '?tab=menu')


@restaurant_required
@require_POST
def restaurant_delete_item(request, pk):
    item = get_object_or_404(FoodItem, pk=pk, vendor=request.restaurant)
    name = item.name; item.delete()
    messages.success(request, f'"{name}" removed.')
    return redirect(reverse('food:restaurant_dashboard') + '?tab=menu')


@restaurant_required
@require_POST
def restaurant_add_category(request):
    name = request.POST.get('name','').strip()
    if name:
        FoodCategory.objects.create(vendor=request.restaurant, name=name)
        messages.success(request, f'Category "{name}" added.')
    return redirect(reverse('food:restaurant_dashboard') + '?tab=menu')


@restaurant_required
def restaurant_settings(request):
    r = request.restaurant
    if request.method == 'POST':
        r.name=request.POST.get('name',r.name).strip()
        r.description=request.POST.get('description','').strip()
        r.cuisine=request.POST.get('cuisine',r.cuisine)
        r.address=request.POST.get('address',r.address).strip()
        r.city=request.POST.get('city',r.city).strip()
        r.phone=request.POST.get('phone',r.phone).strip()
        r.whatsapp=request.POST.get('whatsapp','').strip()
        r.opening_time=request.POST.get('opening_time','08:00')
        r.closing_time=request.POST.get('closing_time','22:00')
        r.status=request.POST.get('status',r.status)
        try: r.min_order=Decimal(request.POST.get('min_order',str(r.min_order)))
        except InvalidOperation: pass
        try: r.avg_prep_time=int(request.POST.get('avg_prep_time',str(r.avg_prep_time)))
        except ValueError: pass
        lat=request.POST.get('latitude','').strip(); lng=request.POST.get('longitude','').strip()
        r.latitude=float(lat) if lat else None; r.longitude=float(lng) if lng else None
        if 'logo'   in request.FILES: r.logo   = request.FILES['logo']
        if 'banner' in request.FILES: r.banner = request.FILES['banner']
        r.save(); messages.success(request,'Settings saved.')
        return redirect('food:restaurant_settings')
    return render(request,'food/restaurant_settings.html',{
        'vendor':r,'restaurant':r,'cuisines':FoodVendor.CuisineType.choices,
        'statuses':FoodVendor.Status.choices,'cart_count':0,
        'locationiq_key':getattr(settings,'LOCATIONIQ_API_KEY',''),
    })


# ── Cart HTML page ─────────────────────────────────────────────────────────────

@login_required
def cart_page(request):
    cart      = _get_cart(request.user)
    items     = _cart_items(cart) if cart else []
    subtotal  = _cart_subtotal(cart) if cart else Decimal('0')
    return render(request, 'food/cart.html', {
        'cart':          cart,
        'cart_items':    items,
        'cart_vendor':   cart.vendor if cart else None,
        'cart_subtotal': subtotal,
        'delivery_fee':  MIN_FARE,
        'cart_total':    subtotal + MIN_FARE,
        'cart_count':    _cart_count(cart) if cart else 0,
        'food_cart_count': _cart_count(cart) if cart else 0,
    })


# ── Cart APIs ──────────────────────────────────────────────────────────────────

@login_required
@require_POST
def cart_add(request, item_id):
    try:
        food = get_object_or_404(FoodItem, pk=item_id, is_available=True)

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

        if cart.vendor and cart.vendor_id != food.vendor_id:
            return JsonResponse({
                'success': False, 'conflict': True,
                'message': (f'Your cart has items from {cart.vendor.name}. '
                            'Clear it first to order from this restaurant.'),
            })

        cart.vendor = food.vendor
        cart.save()

        ci, created = FoodCartItem.objects.get_or_create(
            cart=cart, food=food,
            defaults={'quantity': qty, 'note': note},
        )
        if not created:
            ci.quantity += qty
            ci.note = note
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

        # Single clean ownership-verified lookup
        try:
            ci = FoodCartItem.objects.select_related('cart', 'food').get(pk=item_id)
        except FoodCartItem.DoesNotExist:
            return JsonResponse({'success': False, 'error': 'Item not found'}, status=404)

        if not _cart_owns(ci.cart, request.user):
            return JsonResponse({'success': False, 'error': 'Not your cart'}, status=403)

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

        cart  = _get_cart(request.user)
        count = _cart_count(cart) if cart else 0
        total = str(_cart_subtotal(cart)) if cart else '0'

        return JsonResponse({
            'success': True, 'cart_count': count, 'count': count,
            'cart_total': total, 'total': total, 'new_total': new_total,
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
            'success': True,
            'count': count, 'cart_count': count,
            'total': str(subtotal), 'cart_total': str(subtotal),
            'subtotal': str(subtotal), 'delivery': str(MIN_FARE),
            'vendor':      cart.vendor.name if cart and cart.vendor else None,
            'vendor_slug': cart.vendor.slug if cart and cart.vendor else None,
            'items': [{
                'id': i.pk, 'name': i.food.name,
                'price': str(_item_price(i.food)), 'quantity': i.quantity,
                'subtotal': str(_item_line_total(i)),
                'image': getattr(i.food, 'image_url', '') or '',
                'note': i.note or '',
            } for i in items if i.food],
        })
    except Exception as e:
        return JsonResponse({'success': False, 'count': 0, 'total': '0', 'items': [], 'error': str(e)})


def price_estimate(request):
    try:
        dist = haversine_distance(
            float(request.GET.get('vlat')), float(request.GET.get('vlng')),
            float(request.GET.get('dlat')), float(request.GET.get('dlng')))
        fee  = calculate_delivery_fee(dist)
        eta  = estimate_eta(dist, int(request.GET.get('prep', 20)))
        return JsonResponse({'success': True, 'distance_km': round(dist, 2), 'fee': str(fee), 'eta_minutes': eta})
    except (TypeError, ValueError) as e:
        return JsonResponse({'success': False, 'error': str(e)})


# ── Checkout ───────────────────────────────────────────────────────────────────

@login_required
def checkout(request):
    cart = _get_cart(request.user)
    if not cart or not _cart_items(cart).exists():
        messages.error(request, 'Your cart is empty.')
        return redirect('food:home')

    vendor       = cart.vendor
    cart_items   = _cart_items(cart)
    subtotal     = _cart_subtotal(cart)
    delivery_fee = MIN_FARE

    def ctx(errors=None):
        return {
            'cart': cart, 'cart_vendor': vendor, 'vendor': vendor,
            'cart_items': cart_items, 'cart_subtotal': subtotal,
            'delivery_fee': delivery_fee, 'cart_total': subtotal + delivery_fee,
            'subtotal': subtotal, 'default_fee': str(MIN_FARE), 'cart_count': 0,
            'payment_methods': FoodOrder.PaymentMethod.choices,
            'vendor_lat': vendor.latitude or '' if vendor else '',
            'vendor_lng': vendor.longitude or '' if vendor else '',
            'locationiq_key': getattr(settings, 'LOCATIONIQ_API_KEY', ''),
            'errors': errors or {},
        }

    if request.method != 'POST':
        return render(request, 'food/checkout.html', ctx())

    address    = request.POST.get('delivery_address', '').strip()
    phone      = request.POST.get('delivery_phone', '').strip()
    note       = request.POST.get('delivery_note', '').strip()
    pay_method = request.POST.get('payment_method', 'cash')
    dlat       = request.POST.get('delivery_lat', '').strip()
    dlng       = request.POST.get('delivery_lng', '').strip()

    errors = {}
    if not phone:
        errors['phone'] = 'Please enter your phone number.'
    if errors:
        return render(request, 'food/checkout.html', ctx(errors))

    # Address text is helpful but not blocking — GPS coordinates are the
    # authoritative delivery location. If address is blank, build a fallback.
    if not address:
        if dlat and dlng:
            address = f'GPS location ({float(dlat):.4f}, {float(dlng):.4f})'
        else:
            address = 'Ghana'   # safe fallback — rider will call customer

    try:
        delivery_fee = Decimal(request.POST.get('delivery_fee', str(MIN_FARE)))
    except (InvalidOperation, ValueError):
        delivery_fee = MIN_FARE

    try:
        distance_km = float(request.POST.get('distance_km', '3'))
    except ValueError:
        distance_km = 3.0

    order = FoodOrder.objects.create(
        customer=request.user, vendor=vendor,
        delivery_address=address,
        delivery_lat=float(dlat) if dlat else 5.6037,
        delivery_lng=float(dlng) if dlng else -0.1870,
        delivery_phone=phone, delivery_note=note,
        subtotal=subtotal, delivery_fee=delivery_fee,
        distance_km=distance_km, payment_method=pay_method,
        payment_status=FoodOrder.PaymentStatus.UNPAID,
        estimated_delivery_time=estimate_eta(distance_km, vendor.avg_prep_time if vendor else 20),
    )

    for ci in cart_items:
        FoodOrderItem.objects.create(
            order=order, food=ci.food, name=ci.food.name,
            price=_item_price(ci.food), quantity=ci.quantity, note=ci.note or '',
        )

    # Record commission split immediately for ALL payment types
    # (cash, MoMo on delivery, Hubtel prepaid)
    _record_food_earnings(order)

    # Optional: create delivery record
    if _HAS_DELIVERY and Delivery is not None:
        try:
            zone = DeliveryZone.objects.filter(is_active=True).first()
            dr = Delivery.objects.create(
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
            order.delivery = dr
            order.save(update_fields=['delivery'])
        except Exception:
            pass

    if vendor:
        try:
            vendor.total_orders = (vendor.total_orders or 0) + 1
            vendor.save(update_fields=['total_orders'])
        except Exception:
            pass

    _cart_items(cart).delete()
    cart.vendor = None
    cart.save()

    momo_prepaid = getattr(getattr(FoodOrder, 'PaymentMethod', None), 'MOMO_PREPAID', 'momo_prepaid')
    if pay_method == momo_prepaid and _HAS_FOOD_PAYMENT:
        return food_payment_initiate(request, order.order_ref)

    try:
        from delivery.services import auto_assign_for_food_order
        auto_assign_for_food_order(order)
    except Exception:
        pass

    # Show confirmation page for cash / MoMo on delivery
    return render(request, 'food/order_placed.html', {
        'order':       order,
        'order_total': str(_order_total(order)),
        'pay_method':  pay_method,
    })


# ── Order views ────────────────────────────────────────────────────────────────

@login_required
def order_track(request, ref):
    order = get_object_or_404(FoodOrder, order_ref=ref, customer=request.user)
    return render(request, 'food/track.html', {
        'order': order, 'cart_count': 0,
        'locationiq_key': getattr(settings, 'LOCATIONIQ_API_KEY', ''),
        'track_api_url': reverse('food:order_track_api', args=[ref]),
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
        rp = order.delivery.rider
        rname  = rp.rider.get_full_name() or rp.rider.phone
        rphone = rp.rider.phone
    return JsonResponse({
        'status': order.status, 'status_label': order.get_status_display(),
        'rider_lat': rlat, 'rider_lng': rlng,
        'rider_name': rname, 'rider_phone': rphone,
        'eta': order.estimated_delivery_time,
        'dropoff_lat': order.delivery_lat, 'dropoff_lng': order.delivery_lng,
    })


@login_required
def order_history(request):
    orders = FoodOrder.objects.filter(customer=request.user).select_related('vendor').prefetch_related('items').order_by('-created_at')
    return render(request, 'food/orders.html', {'orders': orders, 'cart_count': 0})


@login_required
@require_POST
def reorder(request, ref):
    order = get_object_or_404(FoodOrder, order_ref=ref, customer=request.user)
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
            skipped += 1; continue
        ci, created = FoodCartItem.objects.get_or_create(
            cart=cart, food=food,
            defaults={'quantity': item.quantity, 'note': item.note or ''},
        )
        if not created:
            ci.quantity += item.quantity; ci.save()
        added += 1
    if added:   messages.success(request, f'✅ {added} item{"s" if added != 1 else ""} added to cart.')
    if skipped: messages.warning(request, f'⚠ {skipped} item{"s" if skipped != 1 else ""} unavailable.')
    return redirect('food:menu', slug=vendor.slug)


# ── Food payment ───────────────────────────────────────────────────────────────

def _order_total(order):
    """
    Return the order total safely.
    FoodOrder may have a total_amount field, a total property,
    or just subtotal + delivery_fee — try all three.
    """
    for attr in ('total_amount', 'total'):
        val = getattr(order, attr, None)
        if val is not None and not callable(val):
            return Decimal(str(val))
        if callable(val):
            try:
                return Decimal(str(val()))
            except Exception:
                pass
    return (
        Decimal(str(order.subtotal      or 0)) +
        Decimal(str(order.delivery_fee  or 0))
    ).quantize(Decimal('0.01'))

@login_required
def food_payment_initiate(request, order_ref):
    """
    Initiate Hubtel hosted checkout for a food order.
    Redirects customer to Hubtel's payment page.
    After payment:
      - Hubtel fires webhook → food_payment_webhook → _mark_food_paid
      - Hubtel redirects browser → food_payment_callback → tracking page
    """
    # ── Hubtel credentials guard ───────────────────────────────────────
    # If Hubtel is not yet configured, treat the order as cash-on-delivery
    # so the app doesn't crash. Remove this block once credentials are live.
    _hubtel_ready = bool(
        getattr(settings, 'HUBTEL_CLIENT_ID',     '') and
        getattr(settings, 'HUBTEL_CLIENT_SECRET', '') and
        getattr(settings, 'HUBTEL_MERCHANT_ACCT', '')
    )
    if not _hubtel_ready:
        # Mark as pending cash order — rider collects on delivery
        try:
            order = FoodOrder.objects.get(order_ref=order_ref)
            order.payment_method = FoodOrder.PaymentMethod.CASH_ON_DELIVERY
            order.save(update_fields=['payment_method'])
        except Exception:
            pass
        messages.info(
            request,
            'Online payment is being set up. Your order is confirmed — '
            'please pay your rider on delivery. 🛵'
        )
        return redirect('food:order_track', ref=order_ref)

    if not _HAS_FOOD_PAYMENT:
        # No FoodPayment model — treat as cash order
        messages.success(request, f'Order {order_ref} placed!')
        return redirect('food:order_track', ref=order_ref)

    try:
        order = FoodOrder.objects.get(order_ref=order_ref, customer=request.user)
    except FoodOrder.DoesNotExist:
        messages.error(request, 'Order not found.')
        return redirect('food:order_history')

    # If already paid (e.g. double tap), go straight to tracking
    if order.payment_status == FoodOrder.PaymentStatus.PAID:
        return redirect('food:order_track', ref=order_ref)

    cid   = getattr(settings, 'HUBTEL_CLIENT_ID', '')
    merch = getattr(settings, 'HUBTEL_MERCHANT_ACCT', '')

    if not cid:
        # Hubtel not configured — fall back to cash flow
        import logging
        logging.getLogger(__name__).warning(
            '[FoodPayment] HUBTEL_CLIENT_ID not set — order %s treated as cash', order_ref)
        messages.success(request, f'Order {order_ref} placed! Pay the rider on delivery.')
        return redirect('food:order_track', ref=order_ref)

    total  = _order_total(order)   # safe regardless of FoodOrder field names
    tx_ref = f'FOOD-{order_ref}'[:36]  # Hubtel clientReference max 36 chars
    base   = request.build_absolute_uri('/').rstrip('/')

    # Record payment intent
    fp, _ = FoodPayment.objects.get_or_create(
        food_order=order,
        defaults={
            'amount':         total,
            'transaction_id': tx_ref,
            'momo_number':    order.delivery_phone or '',
            'provider':       'hubtel',
            'status':         FoodPayment.Status.PENDING,
        },
    )

    try:
        resp = http_requests.post(
            'https://payproxyapi.hubtel.com/items/initiate',
            headers={'Authorization': _hubtel_auth(), 'Content-Type': 'application/json'},
            json={
                'totalAmount':           float(total),
                'description':           re.sub(r'[^a-zA-Z0-9 .,-]', '', f'{order.vendor.name} order Lynctel')[:200],
                'clientReference':       fp.transaction_id,
                'callbackUrl':           f'{base}/food/payment/webhook/',
                'returnUrl':             f'{base}/food/payment/callback/{fp.transaction_id}/',
                'cancellationUrl':       f'{base}/food/order/{order_ref}/',
                'merchantAccountNumber': merch,
            },
            timeout=15,
        )
        data         = resp.json()
        checkout_url = data.get('checkoutUrl') or data.get('checkoutDirectUrl')

        if checkout_url:
            direct_url = data.get('checkoutDirectUrl', '')
            checkout_id = data.get('checkoutId', fp.transaction_id)
            # Persist checkout_id
            try:
                fp.transaction_id = checkout_id
                fp.save(update_fields=['transaction_id'])
            except Exception:
                pass
            # Render iFrame (direct_url) or redirect fallback
            return render(request, 'food/pay.html', {
                'order':        order,
                'checkout_url': checkout_url,
                'direct_url':   direct_url,
                'cart_count':   0,
            })

        # Hubtel returned an error
        import logging
        logging.getLogger(__name__).error(
            '[FoodPayment] Hubtel initiate failed for %s: %s', order_ref, data)
        messages.error(request, data.get('message') or 'Payment could not start. Try again.')

    except Exception as e:
        import logging
        logging.getLogger(__name__).error('[FoodPayment] Exception for %s: %s', order_ref, e)
        messages.error(request, 'Could not reach payment gateway. Try again or pay on delivery.')

    # If we reach here something went wrong — go to tracking so order isn't lost
    return redirect('food:order_track', ref=order_ref)


@login_required
def food_payment_callback(request, tx_ref):
    if not _HAS_FOOD_PAYMENT:
        return redirect('food:home')
    try:
        fp = FoodPayment.objects.select_related('food_order').get(transaction_id=tx_ref)
    except FoodPayment.DoesNotExist:
        messages.error(request, 'Payment record not found.')
        return redirect('food:home')
    order = fp.food_order
    if fp.status == FoodPayment.Status.SUCCESS:
        messages.success(request, f'✅ Order {order.order_ref} confirmed!')
        return redirect('food:order_track', ref=order.order_ref)
    if request.GET.get('status') == 'cancelled':
        fp.status = FoodPayment.Status.FAILED
        fp.save(update_fields=['status'])
        messages.warning(request, 'Payment cancelled.')
        return redirect('food:order_track', ref=order.order_ref)
    return render(request, 'food/payment_processing.html', {
        'order': order,
        'poll_url': reverse('food:payment_status', args=[order.order_ref]),
    })


@csrf_exempt
@require_POST
def food_payment_webhook(request):
    if not _HAS_FOOD_PAYMENT:
        return HttpResponse(status=200)
    try:
        body = json.loads(request.body)
        if body.get('ResponseCode') == '0000':
            data  = body.get('Data', {})
            tx    = data.get('ClientReference', '')
            txnid = data.get('TransactionId', '')
            if tx.startswith('FOOD-'):
                fp = FoodPayment.objects.select_related('food_order').get(transaction_id=tx)
                if fp.status != FoodPayment.Status.SUCCESS:
                    _mark_food_paid(fp, fp.food_order, txnid, {'via': 'webhook'})
    except Exception:
        pass
    return HttpResponse(status=200)


@login_required
def food_payment_status(request, order_ref):
    order = get_object_or_404(FoodOrder, order_ref=order_ref, customer=request.user)
    paid  = order.payment_status == FoodOrder.PaymentStatus.PAID
    return JsonResponse({
        'paid': paid,
        'redirect': reverse('food:order_track', args=[order_ref]) if paid else None,
    })



# ── Commission & payout helpers ────────────────────────────────────────────────

def _detect_momo_network(phone):
    """Detect Ghana MoMo network from phone prefix."""
    phone = str(phone).replace('+233', '0').replace(' ', '').strip()
    if phone.startswith(('024','054','055','059','025','053','058')):
        return 'MTN'
    if phone.startswith(('020','050')):
        return 'VODAFONE'  # Telecel Ghana = Vodafone (rebranded)
    if phone.startswith(('026','056','027','057')):
        return 'AIRTELTIGO'
    return 'MTN'


def _hubtel_transfer(phone, amount, reference, description):
    """
    DISABLED — outgoing transfers removed per business model.
    Lynctel receives commission automatically on customer payment.
    No money is sent out from the app.
    """
    import logging
    logging.getLogger(__name__).warning(
        '[Transfer] _hubtel_transfer called but disabled — '
        'no outgoing transfers. ref=%s amount=%s', reference, amount
    )
    return False  # always returns False — transfer not performed
    """
    Send money to a MoMo number via Hubtel Transfers API.
    Returns True on success, False on failure.
    """
    import logging
    log = logging.getLogger(__name__)
    cid = getattr(settings, 'HUBTEL_CLIENT_ID', '')
    if not cid or not phone or float(amount) <= 0:
        return False
    try:
        # Direct Send Money endpoint — verify with Hubtel partner team
        # Reference: https://developers.hubtel.com/docs/business/api_documentation/payment_apis/direct_send_money
        resp = http_requests.post(
            f'https://api.hubtel.com/v2/merchantaccount/merchants/{getattr(settings, "HUBTEL_MERCHANT_ACCT", "")}/send-money',
            headers={'Authorization': _hubtel_auth(), 'Content-Type': 'application/json'},
            json={
                'amount':              float(amount),
                'receiverMobileNumber': str(phone),
                'networkCode':          _detect_momo_network(phone),
                'description':          description[:100],
                'clientReference':      str(reference)[:36],
            },
            timeout=20,
        )
        data = resp.json()
        ok   = resp.status_code in (200, 201) and data.get('responseCode') in ('0000', '00')
        if not ok:
            log.error('[FoodPayout] Transfer failed %s: %s', reference, data)
        return ok
    except Exception as e:
        log.error('[FoodPayout] Transfer error %s: %s', reference, e)
        return False


def _record_food_earnings(order):
    """
    Record the commission split the moment an order is placed,
    for EVERY payment type (cash, MoMo on delivery, Hubtel prepaid).

    Vendor split  → 96% to vendor / 4% to app
    Rider split   → 95% to rider  / 5% to app

    For cash orders: records what is owed; disbursement happens via
    weekly settlement (vendor pays 4% commission to Lynctel).
    For Hubtel prepaid: actual transfers fired by _disburse_food_payouts().
    """
    if not order.vendor:
        return

    # ── Vendor earnings ──────────────────────────────────────────────────
    item_gross        = Decimal(str(order.subtotal or 0))
    vendor_commission = (item_gross * FOOD_APP_VENDOR_CUT).quantize(Decimal('0.01'))
    vendor_payout     = (item_gross * FOOD_VENDOR_SHARE).quantize(Decimal('0.01'))

    if _HAS_VENDOR_EARNING and FoodVendorEarning is not None:
        FoodVendorEarning.objects.get_or_create(
            food_order=order,
            defaults={
                'vendor':         order.vendor,
                'gross_amount':   item_gross,
                'app_commission': vendor_commission,   # 4%  → stays with Lynctel
                'vendor_payout':  vendor_payout,       # 96% → goes to vendor
                'status':         'pending',
            },
        )

    # ── Rider / delivery earnings ────────────────────────────────────────
    delivery_gross    = Decimal(str(order.delivery_fee or 0))
    rider_commission  = (delivery_gross * FOOD_APP_RIDER_CUT).quantize(Decimal('0.01'))
    rider_payout      = (delivery_gross * FOOD_RIDER_SHARE).quantize(Decimal('0.01'))

    # Update Delivery record with the correct rider earnings (95%)
    if order.delivery and _HAS_DELIVERY and Delivery is not None:
        try:
            order.delivery.rider_commission = rider_payout
            order.delivery.save(update_fields=['rider_commission'])
        except Exception:
            pass


def _disburse_food_payouts(order):
    """
    DISABLED — no outgoing transfers from the app.
    Lynctel's commission is received automatically when the customer pays
    (it sits in the Hubtel merchant account).
    Vendor/rider earnings are recorded in DB via _record_food_earnings()
    for accounting and manual settlement tracking only.
    """""
    # No-op: commission already in merchant account. DB records updated separately.
    return  # intentionally empty
    import logging
    log = logging.getLogger(__name__)




def _pay_rider_on_delivery(order):
    """
    DISABLED — no outgoing transfers from the app.
    Rider's 95% share is recorded in DB by _record_food_earnings().
    Rider payout is handled offline / via staff settlement dashboard.
    """""
    return  # no outgoing transfer — commission received on customer payment



def _mark_food_paid(fp, order, gateway_ref, gateway_data):
    with transaction.atomic():
        fp.status = FoodPayment.Status.SUCCESS
        fp.gateway_ref = gateway_ref
        fp.gateway_response = gateway_data
        fp.paid_at = timezone.now()
        fp.save()
        order.payment_status = FoodOrder.PaymentStatus.PAID
        order.status         = FoodOrder.Status.CONFIRMED
        order.confirmed_at   = timezone.now()
        order.save(update_fields=['payment_status', 'status', 'confirmed_at'])

    # Commission is already received in Lynctel's Hubtel merchant account.
    # _record_food_earnings() has already logged the split for accounting.
    # No outgoing transfers — vendors/riders settle via dashboard.
    try:
        from delivery.services import auto_assign_for_food_order
        auto_assign_for_food_order(order)
    except Exception:
        pass

# ── Saved delivery addresses (item 8) ─────────────────────────────────────────

import json as _json

@require_GET
@login_required
def saved_address_list(request):
    """GET /food/addresses/ — returns user's saved addresses as JSON."""
    try:
        from food.models import SavedAddress
        addrs = SavedAddress.objects.filter(customer=request.user).order_by('-is_default', '-created_at')[:5]
        return JsonResponse({'addresses': [
            {
                'id':         a.pk,
                'label':      a.label,
                'address':    a.address,
                'lat':        a.latitude,
                'lng':        a.longitude,
                'is_default': a.is_default,
            }
            for a in addrs
        ]})
    except Exception as e:
        return JsonResponse({'addresses': [], 'error': str(e)})


@require_POST
@login_required
def saved_address_save(request):
    """POST /food/addresses/save/ — save current checkout address."""
    try:
        from food.models import SavedAddress
        d       = _json.loads(request.body)
        label   = d.get('label', 'Home').strip() or 'Home'
        address = d.get('address', '').strip()
        lat     = float(d.get('lat', 0))
        lng     = float(d.get('lng', 0))

        if not address or not lat or not lng:
            return JsonResponse({'success': False, 'error': 'Missing fields'})

        existing = SavedAddress.objects.filter(customer=request.user)
        if existing.count() >= 5:
            existing.order_by('created_at').first().delete()

        addr = SavedAddress.objects.create(
            customer=request.user, label=label,
            address=address, latitude=lat, longitude=lng,
        )
        return JsonResponse({'success': True, 'id': addr.pk})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


@require_POST
@login_required
def saved_address_delete(request, pk):
    """POST /food/addresses/<pk>/delete/ — remove a saved address."""
    try:
        from food.models import SavedAddress
        SavedAddress.objects.filter(pk=pk, customer=request.user).delete()
        return JsonResponse({'success': True})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


# ── Food item ratings (item 9) ─────────────────────────────────────────────────

@login_required
def rate_food_order(request, order_ref):
    """
    GET/POST /food/rate/<order_ref>/
    Customer rates each item in a delivered food order.
    Triggered via SMS link sent after delivery.
    """
    try:
        from food.models import FoodOrder
        order = get_object_or_404(FoodOrder, order_ref=order_ref, customer=request.user)
    except Exception:
        messages.error(request, 'Order not found.')
        return redirect('food:order_history')

    if request.method == 'POST':
        _save_food_ratings(request, order)
        messages.success(request, 'Thank you for your rating! 🌟')
        return redirect('food:order_history')

    return render(request, 'food/rate_order.html', {
        'order':      order,
        'cart_count': 0,
    })


def _save_food_ratings(request, order):
    """Save star ratings for each item in the order."""
    try:
        from food.models import FoodReview
        for item in order.items.select_related('food').all():
            rating = int(request.POST.get(f'rating_{item.pk}', 0))
            if 1 <= rating <= 5:
                FoodReview.objects.update_or_create(
                    food_order=order,
                    food_item=item.food,
                    customer=request.user,
                    defaults={
                        'rating':  rating,
                        'comment': request.POST.get(f'comment_{item.pk}', '').strip(),
                    },
                )
    except Exception:
        pass

@login_required
def food_payment_return(request, order_ref):
    """
    Browser return URL after Hubtel checkout (iFrame postMessage or redirect).
    Checks payment status and routes accordingly:
      - Paid   → order tracking page
      - Pending → payment processing page (polls every 3s)
      - Failed  → order history with error message
    """
    from food.models import FoodOrder
    try:
        order = FoodOrder.objects.get(order_ref=order_ref, customer=request.user)
    except FoodOrder.DoesNotExist:
        messages.error(request, 'Order not found.')
        return redirect('food:order_history')

    if order.payment_status == 'paid':
        return redirect('food:order_track', ref=order_ref)

    if order.payment_status == 'failed':
        messages.error(request, 'Payment failed. Please try again.')
        return redirect('food:order_history')

    # Pending — show processing page which polls every 3s
    return render(request, 'food/payment_processing.html', {
        'order':      order,
        'poll_url':   request.build_absolute_uri(
                          f'/food/payment/status/{order_ref}/'),
        'cancel_url': request.build_absolute_uri('/food/orders/'),
        'cart_count': 0,
    })
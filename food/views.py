
import math
import json
import uuid
import hmac
import hashlib
import requests
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse, HttpResponse
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
from django.db import transaction
from django.db.models import Q, Sum

from .models import (
    FoodVendor, FoodCategory, FoodItem,
    FoodOrder, FoodOrderItem, FoodCart, FoodCartItem,
    FoodPayment, FoodVendorEarning,
)
from delivery.models import Delivery, DeliveryZone


# ─────────────────────────────
# COMMISSION RATES
# ─────────────────────────────
FOOD_VENDOR_SHARE = Decimal('0.96')   # 96% to vendor
FOOD_APP_SHARE    = Decimal('0.04')   # 4%  to Lynctel


def _notify_food_status(order, new_status):
    try:
        from delivery.notifications import notify_food_order_status_change
        notify_food_order_status_change(order, new_status)
    except Exception:
        pass


# ─────────────────────────────
# PRICING ENGINE
# ─────────────────────────────
BASE_FARE    = Decimal('5.00')
PER_KM_RATE  = Decimal('2.50')
MIN_FARE     = Decimal('8.00')
SURGE_FACTOR = Decimal('1.0')


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


# ─────────────────────────────
# GUARD DECORATOR
# ─────────────────────────────
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


# ─────────────────────────────
# PUBLIC: FOOD HOME
# ─────────────────────────────
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
                    float(user_lat), float(user_lng),
                    v.latitude, v.longitude
                ), 1)
                eta = estimate_eta(distance, v.avg_prep_time)
            except Exception:
                pass
        vendor_list.append({'vendor': v, 'distance': distance, 'eta': eta})

    vendor_list.sort(key=lambda x: x['distance'] if x['distance'] is not None else 999)

    return render(request, 'food/home.html', {
        'vendor_list':      vendor_list,
        'cuisines':         FoodVendor.CuisineType.choices,
        'selected_cuisine': cuisine,
        'query':            query,
        'food_cart_count':  _get_food_cart_count(request),
        'cart_count':       0,
    })


# ─────────────────────────────
# PUBLIC: VENDOR MENU
# ─────────────────────────────
def vendor_menu(request, slug):
    vendor     = get_object_or_404(FoodVendor, slug=slug)
    categories = vendor.food_categories.prefetch_related('items').all()
    all_items  = vendor.food_items.filter(is_available=True).select_related('category')

    uncategorized_items = all_items.filter(category__isnull=True)
    featured_items      = all_items.filter(is_featured=True)[:10]

    food_cart_count = 0
    cart_vendor_id  = None
    if request.user.is_authenticated:
        try:
            cart = request.user.food_cart
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
        'food_cart_count':     food_cart_count,
        'cart_vendor_id':      cart_vendor_id,
        'cart_count':          0,
    })


# ─────────────────────────────
# RESTAURANT REGISTRATION
# ─────────────────────────────
@login_required
def register_restaurant(request):
    if FoodVendor.objects.filter(owner=request.user).exists():
        return redirect('food:restaurant_dashboard')

    if request.method == 'POST':
        name         = request.POST.get('name', '').strip()
        description  = request.POST.get('description', '').strip()
        cuisine      = request.POST.get('cuisine', '')
        address      = request.POST.get('address', '').strip()
        city         = request.POST.get('city', 'Accra').strip()
        phone        = request.POST.get('phone', '').strip()
        whatsapp     = request.POST.get('whatsapp', '').strip()
        opening_time = request.POST.get('opening_time', '08:00')
        closing_time = request.POST.get('closing_time', '22:00')
        min_order    = request.POST.get('min_order', '10')
        avg_prep     = request.POST.get('avg_prep_time', '20')
        latitude     = request.POST.get('latitude', '').strip()
        longitude    = request.POST.get('longitude', '').strip()

        errors = {}
        if not name:    errors['name']    = 'Restaurant name is required.'
        if not address: errors['address'] = 'Address is required.'
        if not phone:   errors['phone']   = 'Phone number is required.'
        if not cuisine: errors['cuisine'] = 'Please select a cuisine type.'

        if errors:
            return render(request, 'food/register.html', {
                'errors':     errors,
                'form_data':  request.POST,
                'cuisines':   FoodVendor.CuisineType.choices,
                'cart_count': 0,
            })

        restaurant = FoodVendor(
            owner         = request.user,
            name          = name,
            description   = description,
            cuisine       = cuisine,
            address       = address,
            city          = city,
            phone         = phone,
            whatsapp      = whatsapp,
            opening_time  = opening_time,
            closing_time  = closing_time,
            min_order     = Decimal(min_order),
            avg_prep_time = int(avg_prep),
            latitude      = float(latitude)  if latitude  else None,
            longitude     = float(longitude) if longitude else None,
            status        = FoodVendor.Status.OPEN,
        )
        if 'logo'   in request.FILES: restaurant.logo   = request.FILES['logo']
        if 'banner' in request.FILES: restaurant.banner = request.FILES['banner']
        restaurant.save()

        messages.success(request, f'🎉 "{name}" is now live on Lynctel Food!')
        return redirect('food:restaurant_dashboard')

    return render(request, 'food/register.html', {
        'cuisines':   FoodVendor.CuisineType.choices,
        'cart_count': 0,
    })


# ─────────────────────────────
# RESTAURANT DASHBOARD
# ─────────────────────────────
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
        'restaurant':     restaurant,
        'tab':            tab,
        'total_orders':   total_orders,
        'active_orders':  active_orders,
        'total_revenue':  total_revenue,
        'today_orders':   today_orders,
        'orders':         orders[:50],
        'status_filter':  status_filter,
        'categories':     categories,
        'all_items':      all_items,
        'status_choices': FoodOrder.Status.choices,
        'cart_count':     0,
    })


# ─────────────────────────────
# UPDATE ORDER STATUS
# ─────────────────────────────
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

    return redirect('/food/dashboard/?tab=orders')


# ─────────────────────────────
# ADD MENU ITEM
# ─────────────────────────────
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

        if errors:
            return render(request, 'food/item_form.html', {
                'restaurant': restaurant, 'categories': categories,
                'errors': errors, 'form_data': request.POST,
                'action': 'Add', 'item': None, 'cart_count': 0,
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
            return redirect('/food/dashboard/?tab=menu')
        except Exception as e:
            messages.error(request, f'Could not save item: {e}')
            return render(request, 'food/item_form.html', {
                'restaurant': restaurant, 'categories': categories,
                'errors': {'name': 'Something went wrong. Please try again.'},
                'form_data': request.POST, 'action': 'Add',
                'item': None, 'cart_count': 0,
            })

    return render(request, 'food/item_form.html', {
        'restaurant': restaurant, 'categories': categories,
        'action': 'Add', 'item': None, 'cart_count': 0,
    })


# ─────────────────────────────
# EDIT MENU ITEM
# ─────────────────────────────
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

        if errors:
            return render(request, 'food/item_form.html', {
                'restaurant': restaurant, 'categories': categories,
                'errors': errors, 'form_data': request.POST,
                'action': 'Edit', 'item': item, 'cart_count': 0,
            })

        item.name = name; item.description = description
        item.category_id = category_id; item.price = price
        item.discount_price = discount_price; item.prep_time = prep_time
        item.is_available = is_available; item.is_featured = is_featured
        item.is_spicy = is_spicy; item.is_vegan = is_vegan
        if 'image' in request.FILES:
            item.image = request.FILES['image']
        item.save()
        messages.success(request, f'"{item.name}" updated.')
        return redirect('/food/dashboard/?tab=menu')

    return render(request, 'food/item_form.html', {
        'restaurant': restaurant, 'categories': categories,
        'item': item, 'action': 'Edit', 'cart_count': 0,
    })


# ─────────────────────────────
# DELETE MENU ITEM
# ─────────────────────────────
@restaurant_required
@require_POST
def restaurant_delete_item(request, pk):
    item = get_object_or_404(FoodItem, pk=pk, vendor=request.restaurant)
    name = item.name
    item.delete()
    messages.success(request, f'"{name}" removed from menu.')
    return redirect('/food/dashboard/?tab=menu')


# ─────────────────────────────
# ADD CATEGORY
# ─────────────────────────────
@restaurant_required
@require_POST
def restaurant_add_category(request):
    name = request.POST.get('name', '').strip()
    if name:
        FoodCategory.objects.create(vendor=request.restaurant, name=name)
        messages.success(request, f'Category "{name}" added.')
    return redirect('/food/dashboard/?tab=menu')


# ─────────────────────────────
# RESTAURANT SETTINGS
# ─────────────────────────────
@restaurant_required
def restaurant_settings(request):
    restaurant = request.restaurant

    if request.method == 'POST':
        restaurant.name        = request.POST.get('name', restaurant.name).strip()
        restaurant.description = request.POST.get('description', '').strip()
        restaurant.cuisine     = request.POST.get('cuisine', restaurant.cuisine)
        restaurant.address     = request.POST.get('address', restaurant.address).strip()
        restaurant.city        = request.POST.get('city', restaurant.city).strip()
        restaurant.phone       = request.POST.get('phone', restaurant.phone).strip()
        restaurant.whatsapp    = request.POST.get('whatsapp', '').strip()
        restaurant.opening_time = request.POST.get('opening_time', '08:00')
        restaurant.closing_time = request.POST.get('closing_time', '22:00')
        restaurant.status      = request.POST.get('status', restaurant.status)

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
        'restaurant': restaurant,
        'cuisines':   FoodVendor.CuisineType.choices,
        'statuses':   FoodVendor.Status.choices,
        'cart_count': 0,
    })


# ─────────────────────────────
# CART APIs
# ─────────────────────────────
@login_required
@require_POST
def cart_add(request, item_id):
    food = get_object_or_404(FoodItem, pk=item_id, is_available=True)
    try:
        data = json.loads(request.body)
    except Exception:
        data = {}
    qty  = max(1, int(data.get('quantity', 1)))
    note = data.get('note', '')

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
    try:
        data = json.loads(request.body)
    except Exception:
        data = {}
    qty = int(data.get('quantity', 1))

    cart_item = get_object_or_404(FoodCartItem, pk=item_id, cart__customer=request.user)
    if qty <= 0:
        cart_item.delete()
    else:
        cart_item.quantity = qty
        cart_item.save()

    cart = request.user.food_cart
    return JsonResponse({
        'success':    True,
        'cart_count': cart.item_count,
        'cart_total': str(cart.total),
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
        return JsonResponse({
            'success':     True,
            'vendor':      cart.vendor.name if cart.vendor else None,
            'vendor_slug': cart.vendor.slug if cart.vendor else None,
            'count':       cart.item_count,
            'total':       str(cart.total),
            'items': [
                {
                    'id':       i.pk,
                    'name':     i.food.name,
                    'price':    str(i.food.final_price),
                    'quantity': i.quantity,
                    'subtotal': str(i.subtotal),
                    'image':    i.food.image_url,
                    'note':     i.note,
                }
                for i in items
            ],
        })
    except Exception:
        return JsonResponse({'success': True, 'count': 0, 'total': '0', 'items': [], 'vendor': None})


# ─────────────────────────────
# PRICING API
# ─────────────────────────────
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

    return JsonResponse({
        'success':     True,
        'distance_km': round(distance, 2),
        'fee':         str(fee),
        'eta_minutes': eta,
    })


# ─────────────────────────────
# CHECKOUT
# ─────────────────────────────
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
    locationiq_key = settings.LOCATIONIQ_API_KEY

    if request.method == 'POST':
        address    = request.POST.get('delivery_address', '').strip()
        phone      = request.POST.get('delivery_phone', '').strip()
        note       = request.POST.get('delivery_note', '').strip()
        pay_method = request.POST.get('payment_method', 'cash')
        dlat       = request.POST.get('delivery_lat', '').strip()
        dlng       = request.POST.get('delivery_lng', '').strip()
        fee_posted = request.POST.get('delivery_fee', '0')
        dist_posted = request.POST.get('distance_km', '0')

        errors = {}
        if not address: errors['address'] = 'Please enter your delivery address.'
        if not phone:   errors['phone']   = 'Please enter your phone number.'

        if errors:
            return render(request, 'food/checkout.html', {
                'cart':            cart,
                'vendor':          vendor,
                'cart_items':      cart.cart_items.select_related('food').all(),
                'subtotal':        cart.total,
                'default_fee':     str(MIN_FARE),
                'user':            request.user,
                'cart_count':      0,
                'payment_methods': FoodOrder.PaymentMethod.choices,
                'vendor_lat':      vendor.latitude  or '',
                'vendor_lng':      vendor.longitude or '',
                'errors':          errors,
                'locationiq_key':  locationiq_key,
            })

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

        for ci in cart.cart_items.select_related('food').all():
            FoodOrderItem.objects.create(
                order=order, food=ci.food, name=ci.food.name,
                price=ci.food.final_price, quantity=ci.quantity, note=ci.note,
            )

        zone = DeliveryZone.objects.filter(is_active=True).first()
        delivery_record = Delivery.objects.create(
            booker           = request.user,
            pickup_location  = vendor.address,
            dropoff_location = address,
            pickup_lat       = vendor.latitude,
            pickup_lng       = vendor.longitude,
            dropoff_lat      = float(dlat) if dlat else None,
            dropoff_lng      = float(dlng) if dlng else None,
            delivery_fee     = delivery_fee,
            rider_commission = delivery_fee * Decimal('0.5'),
            distance_km      = distance_km,
            zone             = zone,
            delivery_type    = Delivery.DeliveryType.EXPRESS,
            status           = Delivery.Status.PENDING,
            delivery_note    = note,
        )
        order.delivery = delivery_record
        order.save(update_fields=['delivery'])

        vendor.total_orders += 1
        vendor.save(update_fields=['total_orders'])

        cart.cart_items.all().delete()
        cart.vendor = None
        cart.save()

        # ── Route by payment method ──────────────────────────────────────────
        if pay_method == FoodOrder.PaymentMethod.MOMO_PREPAID:
            # Redirect to Paystack — rider assigned AFTER payment confirmed
            return food_payment_initiate(request, order.order_ref)

        # Cash or MoMo on delivery — assign rider now
        try:
            from delivery.services import auto_assign_for_food_order
            auto_assign_for_food_order(order)
        except Exception:
            pass

        pay_msg = {
            'cash':             'Pay the rider cash on delivery.',
            'momo_on_delivery': 'Have your MoMo ready for the rider.',
        }.get(pay_method, '')

        messages.success(
            request,
            f'✅ Order {order.order_ref} placed! {pay_msg} '
            f'Estimated delivery: {order.estimated_delivery_time} mins.'
        )
        return redirect('food:order_track', ref=order.order_ref)

    return render(request, 'food/checkout.html', {
        'cart':            cart,
        'vendor':          vendor,
        'cart_items':      cart.cart_items.select_related('food').all(),
        'subtotal':        cart.total,
        'default_fee':     str(MIN_FARE),
        'user':            request.user,
        'cart_count':      0,
        'payment_methods': FoodOrder.PaymentMethod.choices,
        'vendor_lat':      vendor.latitude  or '',
        'vendor_lng':      vendor.longitude or '',
        'locationiq_key':  locationiq_key,
    })


# ─────────────────────────────
# ORDER TRACKING
# ─────────────────────────────
@login_required
def order_track(request, ref):
    order = get_object_or_404(FoodOrder, order_ref=ref, customer=request.user)
    return render(request, 'food/track.html', {
        'order':          order,
        'cart_count':     0,
        'locationiq_key': settings.LOCATIONIQ_API_KEY,
    })


@login_required
def order_track_api(request, ref):
    order = get_object_or_404(FoodOrder, order_ref=ref, customer=request.user)
    rider_lat = rider_lng = rider_name = rider_phone = None

    if order.delivery and order.delivery.rider:
        try:
            from rider.models import RiderLocation
            loc = RiderLocation.objects.get(
                rider=order.delivery.rider.rider, is_active=True
            )
            rider_lat = float(loc.latitude)
            rider_lng = float(loc.longitude)
        except Exception:
            pass
        rp          = order.delivery.rider
        rider_name  = rp.rider.get_full_name() or rp.rider.phone
        rider_phone = rp.rider.phone

    return JsonResponse({
        'status':       order.status,
        'status_label': order.get_status_display(),
        'rider_lat':    rider_lat,
        'rider_lng':    rider_lng,
        'rider_name':   rider_name,
        'rider_phone':  rider_phone,
        'eta':          order.estimated_delivery_time,
    })


# ─────────────────────────────
# ORDER HISTORY
# ─────────────────────────────
@login_required
def order_history(request):
    orders = FoodOrder.objects.filter(
        customer=request.user
    ).select_related('vendor').prefetch_related('items').order_by('-created_at')
    return render(request, 'food/orders.html', {
        'orders':     orders,
        'cart_count': 0,
    })


# ═══════════════════════════════════════════════════════════════════════════════
# PAYMENT VIEWS
# ═══════════════════════════════════════════════════════════════════════════════

@login_required
def food_payment_initiate(request, order_ref):
    """Initiate Paystack MoMo payment for a food order."""
    food_order = get_object_or_404(
        FoodOrder,
        order_ref=order_ref,
        customer=request.user,
        payment_status=FoodOrder.PaymentStatus.UNPAID,
    )

    # Don't allow double-payment
    if hasattr(food_order, 'payment') and food_order.payment.status == FoodPayment.Status.SUCCESS:
        return redirect('food:order_track', ref=order_ref)

    tx_ref = f"FOOD-{order_ref}-{uuid.uuid4().hex[:6].upper()}"
    email  = request.user.email or f"{request.user.phone}@lynctel.app"
    callback_url = request.build_absolute_uri(f'/food/payment/callback/{tx_ref}/')

    fp, created = FoodPayment.objects.get_or_create(
        food_order=food_order,
        defaults={
            'amount':         food_order.total_amount,
            'transaction_id': tx_ref,
            'momo_number':    food_order.delivery_phone,
            'provider':       'paystack',
            'status':         FoodPayment.Status.PENDING,
        }
    )
    if not created:
        tx_ref = fp.transaction_id  # reuse existing pending record

    payload = {
        'email':        email,
        'amount':       int(float(food_order.total_amount) * 100),
        'currency':     'GHS',
        'reference':    tx_ref,
        'callback_url': callback_url,
        'channels':     ['mobile_money', 'card'],
        'metadata': {
            'food_order_ref': order_ref,
            'food_order_id':  food_order.id,
            'vendor':         food_order.vendor.name if food_order.vendor else '',
            'customer':       request.user.get_full_name() or request.user.phone,
            'phone':          food_order.delivery_phone,
        },
    }

    try:
        resp = requests.post(
            'https://api.paystack.co/transaction/initialize',
            headers={
                'Authorization': f'Bearer {settings.PAYSTACK_SECRET_KEY}',
                'Content-Type':  'application/json',
            },
            json=payload,
            timeout=15,
        )
        data = resp.json()
    except Exception:
        messages.error(request, 'Could not connect to payment gateway. Please try again.')
        return redirect('food:order_track', ref=order_ref)

    if data.get('status'):
        return redirect(data['data']['authorization_url'])
    else:
        messages.error(request, f"Payment error: {data.get('message', 'Please try again.')}")
        return redirect('food:order_track', ref=order_ref)


@login_required
def food_payment_callback(request, tx_ref):
    """Paystack redirects here after the customer pays."""
    try:
        fp = FoodPayment.objects.select_related('food_order').get(transaction_id=tx_ref)
        food_order = fp.food_order
    except FoodPayment.DoesNotExist:
        messages.error(request, 'Payment record not found.')
        return redirect('food:home')

    if fp.status == FoodPayment.Status.SUCCESS:
        messages.success(request, f'✅ Order {food_order.order_ref} confirmed!')
        return redirect('food:order_track', ref=food_order.order_ref)

    try:
        resp = requests.get(
            f'https://api.paystack.co/transaction/verify/{tx_ref}',
            headers={'Authorization': f'Bearer {settings.PAYSTACK_SECRET_KEY}'},
            timeout=15,
        )
        data = resp.json()
    except Exception:
        messages.error(request, 'Could not verify payment. Contact support.')
        return redirect('food:order_track', ref=food_order.order_ref)

    if (
        data.get('status')
        and data['data']['status'] == 'success'
        and data['data']['currency'] == 'GHS'
        and float(data['data']['amount']) >= float(food_order.total_amount) * 100
    ):
        _mark_food_paid(fp, food_order, str(data['data']['id']), {
            'verified_via':     'paystack_callback',
            'channel':          data['data'].get('channel', ''),
            'gateway_response': data['data'].get('gateway_response', ''),
        })
        messages.success(request, f'🎉 Payment confirmed! Order {food_order.order_ref} is being prepared.')
        return redirect('food:order_track', ref=food_order.order_ref)
    else:
        fp.status = FoodPayment.Status.FAILED
        fp.save(update_fields=['status'])
        messages.error(request, '❌ Payment was not completed. Please try again.')
        return redirect('food:order_track', ref=food_order.order_ref)


@csrf_exempt
@require_POST
def food_payment_webhook(request):
    """Paystack webhook — backup in case customer closes browser before redirect."""
    signature = request.headers.get('X-Paystack-Signature', '')
    payload   = request.body

    secret   = settings.PAYSTACK_SECRET_KEY.encode('utf-8')
    computed = hmac.new(secret, payload, hashlib.sha512).hexdigest()
    if not hmac.compare_digest(computed, signature):
        return HttpResponse(status=400)

    try:
        event = json.loads(payload)
    except Exception:
        return HttpResponse(status=400)

    if event.get('event') == 'charge.success':
        data      = event.get('data', {})
        reference = data.get('reference', '')
        metadata  = data.get('metadata', {})

        if not reference.startswith('FOOD-') and 'food_order_ref' not in metadata:
            return HttpResponse(status=200)

        try:
            fp = FoodPayment.objects.select_related('food_order').get(transaction_id=reference)
            food_order = fp.food_order
            if fp.status != FoodPayment.Status.SUCCESS:
                amount_ghs = float(data.get('amount', 0)) / 100
                if amount_ghs >= float(food_order.total_amount):
                    _mark_food_paid(fp, food_order, str(data.get('id', '')), {
                        'verified_via':     'paystack_webhook',
                        'channel':          data.get('channel', ''),
                        'gateway_response': data.get('gateway_response', ''),
                    })
        except FoodPayment.DoesNotExist:
            pass

    return HttpResponse(status=200)


@login_required
def food_payment_status(request, order_ref):
    """AJAX endpoint — tracking page polls this to detect when MoMo payment clears."""
    food_order = get_object_or_404(FoodOrder, order_ref=order_ref, customer=request.user)
    return JsonResponse({
        'payment_status': food_order.payment_status,
        'order_status':   food_order.status,
        'paid':           food_order.payment_status == FoodOrder.PaymentStatus.PAID,
    })


# ─────────────────────────────
# PAYMENT HELPERS
# ─────────────────────────────
def _mark_food_paid(fp, food_order, gateway_ref, gateway_data):
    """Confirm payment, split commission, assign rider — all atomically safe."""
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

    # Assign rider outside the atomic block — rider assignment failure must never
    # roll back a confirmed payment
    try:
        from delivery.services import auto_assign_for_food_order
        auto_assign_for_food_order(food_order)
    except Exception:
        pass


def _split_food_commission(food_order):
    """
    96% of the food subtotal goes to the vendor.
    4% stays with Lynctel as app commission.
    Delivery fee is separate — goes to the rider via RiderEarning.
    """
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


    
@login_required
@require_POST
def reorder(request, ref):
    """
    Adds every item from a past delivered food order back into the cart,
    then redirects to the vendor's menu so the customer can adjust before
    checking out.
 
    Behaviour notes:
    - If the cart already has items from a DIFFERENT vendor, we don't
      silently wipe them — we redirect to the menu with a clear warning
      so the customer can decide.
    - Items that are no longer available (is_available=False or deleted)
      are skipped with an individual warning rather than blocking the
      whole reorder.
    - Stock/availability is re-checked at this point, not at original
      order time, so the customer always sees current prices.
    """
    from food.models import FoodOrder, FoodCart, FoodCartItem
 
    order  = get_object_or_404(FoodOrder, order_ref=ref, customer=request.user)
    vendor = order.vendor
 
    # Get or create the customer's cart
    cart, _ = FoodCart.objects.get_or_create(customer=request.user)
 
    # Conflict: cart already has items from a different restaurant
    if cart.vendor and cart.vendor != vendor and cart.cart_items.exists():
        messages.warning(
            request,
            f'Your cart already has items from {cart.vendor.name}. '
            f'Clear your cart first to reorder from {vendor.name}.'
        )
        return redirect('food:vendor_menu', slug=vendor.slug)
 
    cart.vendor = vendor
    cart.save(update_fields=['vendor'])
 
    added   = 0
    skipped = []
 
    for item in order.items.select_related('food').all():
        food = item.food  # ForeignKey to the original FoodItem
 
        # food might be None if the item was deleted from the menu
        if food is None or not food.is_available:
            skipped.append(item.name)
            continue
 
        cart_item, created = FoodCartItem.objects.get_or_create(
            cart=cart,
            food=food,
            defaults={'quantity': item.quantity, 'note': item.note},
        )
        if not created:
            # Already in cart — bump the quantity
            cart_item.quantity += item.quantity
            cart_item.save(update_fields=['quantity'])
 
        added += 1
 
    if added:
        messages.success(
            request,
            f'✅ {added} item{"s" if added != 1 else ""} added to your cart from {vendor.name}.'
        )
    if skipped:
        messages.warning(
            request,
            f'⚠ {len(skipped)} item{"s" if len(skipped) != 1 else ""} '
            f'no longer available and were skipped: {", ".join(skipped)}.'
        )
    if not added and not skipped:
        messages.info(request, 'No items could be added — the menu may have changed.')
 
    return redirect('food:vendor_menu', slug=vendor.slug)
 
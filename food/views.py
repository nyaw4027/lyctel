import math
import json
from decimal import Decimal

from django.conf import settings
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.utils import timezone
from django.db.models import Q, Sum

from .models import (
    FoodVendor, FoodCategory, FoodItem,
    FoodOrder, FoodOrderItem, FoodCart, FoodCartItem,
)
from delivery.models import Delivery, DeliveryZone
try:
    from delivery.notifications import notify_food_order_status_change
except ImportError:
    notify_food_order_status_change = None


# ─────────────────────────────
# PRICING ENGINE (Uber-style)
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

    food_cart_count = 0
    if request.user.is_authenticated:
        try:
            food_cart_count = request.user.food_cart.item_count
        except Exception:
            pass

    return render(request, 'food/home.html', {
        'vendor_list':      vendor_list,
        'cuisines':         FoodVendor.CuisineType.choices,
        'selected_cuisine': cuisine,
        'query':            query,
        'food_cart_count':  food_cart_count,
        'cart_count':       0,
    })


# ─────────────────────────────
# PUBLIC: VENDOR MENU
# ─────────────────────────────
def vendor_menu(request, slug):
    vendor     = get_object_or_404(FoodVendor, slug=slug)
    categories = vendor.food_categories.prefetch_related('items').all()
    all_items  = vendor.food_items.filter(is_available=True)

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
        'vendor':          vendor,
        'categories':      categories,
        'all_items':       all_items,
        'food_cart_count': food_cart_count,
        'cart_vendor_id':  cart_vendor_id,
        'cart_count':      0,
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
                'errors':    errors,
                'form_data': request.POST,
                'cuisines':  FoodVendor.CuisineType.choices,
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
        if 'logo' in request.FILES:
            restaurant.logo = request.FILES['logo']
        if 'banner' in request.FILES:
            restaurant.banner = request.FILES['banner']
        restaurant.save()

        messages.success(request, f'🎉 "{name}" is now live on Lynctel Food!')
        return redirect('food:restaurant_dashboard')

    return render(request, 'food/register.html', {
        'cuisines':  FoodVendor.CuisineType.choices,
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

    # Stats
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
        'restaurant':    restaurant,
        'tab':           tab,
        'total_orders':  total_orders,
        'active_orders': active_orders,
        'total_revenue': total_revenue,
        'today_orders':  today_orders,
        'orders':        orders[:50],
        'status_filter': status_filter,
        'categories':    categories,
        'all_items':     all_items,
        'status_choices': FoodOrder.Status.choices,
        'cart_count':    0,
    })


# ─────────────────────────────
# UPDATE ORDER STATUS (restaurant)
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

        if notify_food_order_status_change:
            try:
                notify_food_order_status_change(order, new_status)
            except Exception:
                pass
    else:
        messages.error(request, 'Invalid status.')

    return redirect(f'/food/dashboard/?tab=orders')


# ─────────────────────────────
# ADD MENU ITEM
# ─────────────────────────────
@restaurant_required
def restaurant_add_item(request):
    restaurant = request.restaurant
    categories = restaurant.food_categories.all()

    if request.method == 'POST':
        name        = request.POST.get('name', '').strip()
        description = request.POST.get('description', '').strip()
        category_id = request.POST.get('category_id')
        price       = request.POST.get('price', '').strip()
        discount    = request.POST.get('discount_price', '').strip()
        prep_time   = request.POST.get('prep_time', '15')
        is_available = request.POST.get('is_available') == 'on'
        is_featured  = request.POST.get('is_featured') == 'on'
        is_spicy     = request.POST.get('is_spicy') == 'on'
        is_vegan     = request.POST.get('is_vegan') == 'on'

        errors = {}
        if not name:  errors['name']  = 'Item name is required.'
        if not price: errors['price'] = 'Price is required.'

        if errors:
            return render(request, 'food/item_form.html', {
                'restaurant': restaurant, 'categories': categories,
                'errors': errors, 'form_data': request.POST, 'action': 'Add',
                'cart_count': 0,
            })

        item = FoodItem(
            vendor        = restaurant,
            name          = name,
            description   = description,
            category_id   = category_id or None,
            price         = Decimal(price),
            discount_price = Decimal(discount) if discount else None,
            prep_time     = int(prep_time),
            is_available  = is_available,
            is_featured   = is_featured,
            is_spicy      = is_spicy,
            is_vegan      = is_vegan,
        )
        if 'image' in request.FILES:
            item.image = request.FILES['image']
        item.save()

        messages.success(request, f'"{name}" added to your menu!')
        return redirect('/food/dashboard/?tab=menu')

    return render(request, 'food/item_form.html', {
        'restaurant': restaurant, 'categories': categories,
        'action': 'Add', 'cart_count': 0,
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
        item.name          = request.POST.get('name', item.name).strip()
        item.description   = request.POST.get('description', '').strip()
        item.category_id   = request.POST.get('category_id') or None
        item.price         = Decimal(request.POST.get('price', str(item.price)))
        discount           = request.POST.get('discount_price', '').strip()
        item.discount_price = Decimal(discount) if discount else None
        item.prep_time     = int(request.POST.get('prep_time', item.prep_time))
        item.is_available  = request.POST.get('is_available') == 'on'
        item.is_featured   = request.POST.get('is_featured') == 'on'
        item.is_spicy      = request.POST.get('is_spicy') == 'on'
        item.is_vegan      = request.POST.get('is_vegan') == 'on'
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
        restaurant.name          = request.POST.get('name', restaurant.name).strip()
        restaurant.description   = request.POST.get('description', '').strip()
        restaurant.cuisine       = request.POST.get('cuisine', restaurant.cuisine)
        restaurant.address       = request.POST.get('address', restaurant.address).strip()
        restaurant.city          = request.POST.get('city', restaurant.city).strip()
        restaurant.phone         = request.POST.get('phone', restaurant.phone).strip()
        restaurant.whatsapp      = request.POST.get('whatsapp', '').strip()
        restaurant.opening_time  = request.POST.get('opening_time', '08:00')
        restaurant.closing_time  = request.POST.get('closing_time', '22:00')
        restaurant.min_order     = Decimal(request.POST.get('min_order', str(restaurant.min_order)))
        restaurant.avg_prep_time = int(request.POST.get('avg_prep_time', str(restaurant.avg_prep_time)))
        restaurant.status        = request.POST.get('status', restaurant.status)
        lat = request.POST.get('latitude', '').strip()
        lng = request.POST.get('longitude', '').strip()
        restaurant.latitude  = float(lat) if lat else None
        restaurant.longitude = float(lng) if lng else None
        if 'logo' in request.FILES:
            restaurant.logo = request.FILES['logo']
        if 'banner' in request.FILES:
            restaurant.banner = request.FILES['banner']
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
    qty  = int(data.get('quantity', 1))
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

    item, created = FoodCartItem.objects.get_or_create(
        cart=cart, food=food,
        defaults={'quantity': qty, 'note': note},
    )
    if not created:
        item.quantity += qty
        item.note = note
        item.save()

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

    cart_item = get_object_or_404(
        FoodCartItem, pk=item_id, cart__customer=request.user
    )
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

    vendor = cart.vendor

    if request.method == 'POST':
        address     = request.POST.get('delivery_address', '').strip()
        phone       = request.POST.get('delivery_phone', '').strip()
        note        = request.POST.get('delivery_note', '').strip()
        pay_method  = request.POST.get('payment_method', 'cash')
        dlat        = request.POST.get('delivery_lat')
        dlng        = request.POST.get('delivery_lng')
        fee_posted  = request.POST.get('delivery_fee', '0')
        dist_posted = request.POST.get('distance_km', '0')

        errors = {}

        if not address:
            errors['address'] = 'Please enter your delivery address.'

        if not phone:
            errors['phone'] = 'Please enter your phone number.'

        if errors:
            return render(request, 'food/checkout.html', {
                'cart': cart,
                'vendor': vendor,
                'cart_items': cart.cart_items.select_related('food').all(),
                'subtotal': cart.total,
                'default_fee': str(MIN_FARE),
                'user': request.user,
                'cart_count': 0,
                'payment_methods': FoodOrder.PaymentMethod.choices,
                'vendor_lat': vendor.latitude or '',
                'vendor_lng': vendor.longitude or '',
                'errors': errors,
                'locationiq_key': settings.LOCATIONIQ_API_KEY,
            })

        try:
            delivery_fee = Decimal(fee_posted)
            distance_km = float(dist_posted) if dist_posted else None
        except Exception:
            delivery_fee = MIN_FARE
            distance_km = None

        # Create food order
        order = FoodOrder.objects.create(
            customer=request.user,
            vendor=vendor,
            delivery_address=address,
            delivery_lat=float(dlat) if dlat else None,
            delivery_lng=float(dlng) if dlng else None,
            delivery_phone=phone,
            delivery_note=note,
            subtotal=cart.total,
            delivery_fee=delivery_fee,
            distance_km=distance_km,
            payment_method=pay_method,
            payment_status=FoodOrder.PaymentStatus.UNPAID,
            estimated_delivery_time=estimate_eta(
                distance_km or 5,
                vendor.avg_prep_time
            ),
        )

        # Create order items
        for ci in cart.cart_items.select_related('food').all():
            FoodOrderItem.objects.create(
                order=order,
                food=ci.food,
                name=ci.food.name,
                price=ci.food.final_price,
                quantity=ci.quantity,
                note=ci.note,
            )

        # Create delivery record
        zone = DeliveryZone.objects.filter(is_active=True).first()

        delivery = Delivery.objects.create(
            booker=request.user,
            pickup_location=vendor.address,
            dropoff_location=address,
            pickup_lat=vendor.latitude,
            pickup_lng=vendor.longitude,
            dropoff_lat=float(dlat) if dlat else None,
            dropoff_lng=float(dlng) if dlng else None,
            delivery_fee=delivery_fee,
            rider_commission=delivery_fee * Decimal('0.5'),
            distance_km=distance_km,
            zone=zone,
            delivery_type=Delivery.DeliveryType.EXPRESS,
            status=Delivery.Status.PENDING,
            delivery_note=note,
        )

        # Link delivery to food order
        order.delivery = delivery
        order.save(update_fields=['delivery'])

        # Auto assign rider
        try:
            from delivery.services import auto_assign_for_food_order
            auto_assign_for_food_order(order)
        except Exception as e:
            print(f"Auto assignment error: {e}")

        # Update vendor stats
        vendor.total_orders += 1
        vendor.save(update_fields=['total_orders'])

        # Clear cart
        cart.cart_items.all().delete()
        cart.vendor = None
        cart.save()

        messages.success(
            request,
            f'Order {order.order_ref} placed successfully! '
            f'Estimated delivery time: {order.estimated_delivery_time} minutes.'
        )

        return redirect('food:order_track', ref=order.order_ref)

    return render(request, 'food/checkout.html', {
        'cart': cart,
        'vendor': vendor,
        'cart_items': cart.cart_items.select_related('food').all(),
        'subtotal': cart.total,
        'default_fee': str(MIN_FARE),
        'user': request.user,
        'cart_count': 0,
        'payment_methods': FoodOrder.PaymentMethod.choices,
        'vendor_lat': vendor.latitude or '',
        'vendor_lng': vendor.longitude or '',
        'locationiq_key': settings.LOCATIONIQ_API_KEY,
    })


# ─────────────────────────────
# ORDER TRACKING
# ─────────────────────────────
@login_required
def order_track(request, ref):
    order = get_object_or_404(FoodOrder, order_ref=ref, customer=request.user)
    return render(request, 'food/track.html', {
        'order': order,
        'cart_count': 0,
        'locationiq_key': settings.LOCATIONIQ_API_KEY,
    })


@login_required
def order_track_api(request, ref):
    order = get_object_or_404(FoodOrder, order_ref=ref, customer=request.user)
    rider_lat = rider_lng = rider_name = rider_phone = None
    if order.delivery and order.delivery.rider:
        try:
            from rider.models import RiderLocation
            loc = RiderLocation.objects.get(rider=order.delivery.rider.rider, is_active=True)
            rider_lat = float(loc.latitude)
            rider_lng = float(loc.longitude)
        except Exception:
            pass
        rp = order.delivery.rider
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
    return render(request, 'food/orders.html', {'orders': orders, 'cart_count': 0})
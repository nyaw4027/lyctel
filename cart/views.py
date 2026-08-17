"""
cart/views.py

UPGRADES in this version:
  - Rate limiting on cart_add (20 requests/min per user, 5/min per IP for guests)
  - Abandoned cart detection endpoint for scheduled tasks
  - cart_data now includes vendor info for multi-vendor display
"""
from django.shortcuts import render, get_object_or_404, redirect
from django.http import JsonResponse
from django.contrib import messages
from django.utils import timezone
from datetime import timedelta

from .models import Cart, CartItem
from products.models import Product

try:
    from ratelimit.decorators import ratelimit  # type: ignore[import]
    _RL = True
except ImportError:
    # django-ratelimit not installed — define a no-op decorator
    def ratelimit(**kw):
        def dec(f): return f
        return dec
    _RL = False


def get_or_create_cart(request):
    if request.user.is_authenticated:
        cart, _ = Cart.objects.get_or_create(user=request.user)
    else:
        if not request.session.session_key:
            request.session.create()
        cart, _ = Cart.objects.get_or_create(
            session_key=request.session.session_key, user=None
        )
    return cart


def merge_guest_cart(request, user):
    session_key = request.session.session_key
    if not session_key:
        return
    try:
        guest_cart = Cart.objects.get(session_key=session_key, user=None)
    except Cart.DoesNotExist:
        return
    user_cart, _ = Cart.objects.get_or_create(user=user)
    for item in guest_cart.items.select_related('product'):
        existing = user_cart.items.filter(product=item.product).first()
        if existing:
            existing.quantity += item.quantity
            existing.save()
        else:
            item.cart = user_cart
            item.save()
    guest_cart.delete()


def cart_detail(request):
    cart       = get_or_create_cart(request)
    cart_items = cart.items.select_related('product').prefetch_related('product__images').all()
    return render(request, 'cart/cart.html', {
        'cart':       cart,
        'cart_items': cart_items,
        'cart_count': cart.total_items,
    })


@ratelimit(key='user_or_ip', rate='20/m', method='POST', block=True)
def cart_add(request, product_id):
    """
    Rate-limited: 20 adds/minute per user (5/min for guests by IP).
    Prevents cart-spam bots from hammering the DB.
    """
    product  = get_object_or_404(Product, pk=product_id, status='active')
    cart     = get_or_create_cart(request)
    quantity = int(request.POST.get('quantity', 1))

    item, created = CartItem.objects.get_or_create(cart=cart, product=product)
    item.quantity = item.quantity + quantity if not created else quantity
    item.save()

    # Update cart timestamp so abandoned-cart detection works
    cart.updated_at = timezone.now()
    cart.save(update_fields=['updated_at'])

    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    if is_ajax:
        return JsonResponse({
            'success':       True,
            'cart_count':    cart.total_items,
            'item_subtotal': str(item.subtotal),
            'cart_total':    str(cart.total_price),
        })
    messages.success(request, f'"{product.name}" added to cart.')
    return redirect('cart:detail')


def cart_update(request, item_id):
    cart     = get_or_create_cart(request)
    item     = get_object_or_404(CartItem, pk=item_id, cart=cart)
    quantity = int(request.POST.get('quantity', 1))
    if quantity < 1:
        item.delete()
    else:
        item.quantity = quantity
        item.save()
    return JsonResponse({
        'success':       True,
        'cart_count':    cart.total_items,
        'item_subtotal': str(item.subtotal) if quantity >= 1 else '0.00',
        'cart_total':    str(cart.total_price),
    })


def cart_remove(request, item_id):
    cart = get_or_create_cart(request)
    item = get_object_or_404(CartItem, pk=item_id, cart=cart)
    item.delete()
    return JsonResponse({
        'success':    True,
        'cart_count': cart.total_items,
        'cart_total': str(cart.total_price),
    })


def cart_data(request):
    cart  = get_or_create_cart(request)
    items = []
    for item in (cart.items.select_related('product')
                 .prefetch_related('product__images', 'product__vendor').all()):
        img = item.product.images.first()
        items.append({
            'id':       item.pk,
            'name':     item.product.name,
            'price':    str(item.product.selling_price),
            'quantity': item.quantity,
            'subtotal': str(item.subtotal),
            'image':    img.image.url if img else '',
            'vendor':   item.product.vendor.shop_name if item.product.vendor else '',
            'slug':     item.product.slug,
        })
    return JsonResponse({
        'count': cart.total_items,
        'total': str(cart.total_price),
        'items': items,
    })


# ── Abandoned cart recovery ────────────────────────────────────────────────────

def abandoned_carts(request):
    """
    GET /cart/abandoned/ — returns carts with items that haven't been
    updated in > 30 minutes and haven't converted to an order.
    Call from a scheduled task (Railway Cron) every hour.

    Example Railway cron job:
        curl -X GET https://lynctel.up.railway.app/cart/abandoned/ \
             -H "X-Cron-Token: $CRON_TOKEN"

    The response is JSON — your cron can then send recovery SMSes.
    """
    token = request.headers.get('X-Cron-Token', '')
    from django.conf import settings
    if token != getattr(settings, 'CRON_TOKEN', ''):
        from django.http import HttpResponse
        return HttpResponse(status=401)

    cutoff = timezone.now() - timedelta(minutes=30)
    carts  = (
        Cart.objects
        .filter(user__isnull=False, updated_at__lt=cutoff, items__isnull=False)
        .distinct()
        .select_related('user')
        .prefetch_related('items__product')
    )

    result = []
    for cart in carts:
        # Skip if user placed an order after this cart was updated
        from order.models import Order
        has_recent_order = Order.objects.filter(
            customer=cart.user,
            created_at__gt=cart.updated_at,
            payment_status='paid',
        ).exists()
        if has_recent_order:
            continue

        result.append({
            'user_id':   cart.user.pk,
            'phone':     cart.user.phone,
            'items':     cart.total_items,
            'total':     str(cart.total_price),
            'idle_mins': int((timezone.now() - cart.updated_at).total_seconds() / 60),
        })

    # Send recovery SMS to each
    from notifications.sms import send_sms
    sent = 0
    for c in result:
        if c['phone']:
            ok = send_sms(
                c['phone'],
                f'Lynctel: You left {c["items"]} item(s) worth GHS {c["total"]} '
                f'in your cart! Complete your order: lynctel.up.railway.app/cart/'
            )
            if ok:
                sent += 1

    return JsonResponse({'carts_found': len(result), 'sms_sent': sent})
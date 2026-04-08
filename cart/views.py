from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.http import JsonResponse
from products.models import Product
from delivery.models import DeliveryZone
from .models import Cart, CartItem


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
    """Call this right after a user logs in."""
    session_key = request.session.session_key
    if not session_key:
        return
    try:
        guest_cart = Cart.objects.get(session_key=session_key, user=None)
        user_cart, _ = Cart.objects.get_or_create(user=user)
        for item in guest_cart.items.all():
            existing = user_cart.items.filter(product=item.product).first()
            if existing:
                existing.quantity += item.quantity
                existing.save()
            else:
                item.cart = user_cart
                item.save()
        guest_cart.delete()
    except Cart.DoesNotExist:
        pass


def cart_detail(request):
    cart       = get_or_create_cart(request)
    zones      = DeliveryZone.objects.filter(is_active=True)
    cart_items = cart.items.select_related('product').all()
    return render(request, 'cart/cart.html', {
        'cart':       cart,
        'cart_items': cart_items,
        'zones':      zones,
        'cart_count': cart.total_items,
    })


def add_to_cart(request, product_id):
    if request.method != 'POST':
        return redirect('products:list')

    product  = get_object_or_404(Product, pk=product_id, status='active')
    cart     = get_or_create_cart(request)
    quantity = int(request.POST.get('quantity', 1))

    if not product.is_in_stock:
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'message': 'Out of stock.'})
        messages.error(request, f'"{product.name}" is out of stock.')
        return redirect('products:detail', slug=product.slug)

    quantity  = min(quantity, product.stock_qty)
    item, created = CartItem.objects.get_or_create(
        cart=cart, product=product, defaults={'quantity': quantity}
    )
    if not created:
        item.quantity = min(item.quantity + quantity, product.stock_qty)
        item.save()

    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return JsonResponse({
            'success':    True,
            'message':    f'"{product.name}" added to cart.',
            'cart_count': cart.total_items,
            'cart_total': str(cart.total_price),
        })

    messages.success(request, f'"{product.name}" added to cart.')
    return redirect('cart:detail')


def update_cart(request, item_id):
    if request.method != 'POST':
        return redirect('cart:detail')

    cart      = get_or_create_cart(request)
    cart_item = get_object_or_404(CartItem, pk=item_id, cart=cart)
    quantity  = int(request.POST.get('quantity', 1))

    if quantity <= 0:
        cart_item.delete()
    else:
        cart_item.quantity = min(quantity, cart_item.product.stock_qty)
        cart_item.save()

    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return JsonResponse({
            'success':    True,
            'cart_count': cart.total_items,
            'cart_total': str(cart.total_price),
        })
    return redirect('cart:detail')


def remove_from_cart(request, item_id):
    cart      = get_or_create_cart(request)
    cart_item = get_object_or_404(CartItem, pk=item_id, cart=cart)
    name      = cart_item.product.name
    cart_item.delete()
    messages.info(request, f'"{name}" removed from cart.')
    return redirect('cart:detail')
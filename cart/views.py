from django.shortcuts import render, get_object_or_404, redirect
from django.http import JsonResponse
from django.contrib import messages
from .models import Cart, CartItem
from products.models import Product


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


def cart_detail(request):
    cart       = get_or_create_cart(request)
    cart_items = cart.items.select_related('product').prefetch_related('product__images').all()
    return render(request, 'cart/cart.html', {
        'cart':       cart,
        'cart_items': cart_items,
        'cart_count': cart.total_items,
    })


def cart_add(request, product_id):
    product  = get_object_or_404(Product, pk=product_id, status='active')
    cart     = get_or_create_cart(request)
    quantity = int(request.POST.get('quantity', 1))

    item, created = CartItem.objects.get_or_create(cart=cart, product=product)
    item.quantity = item.quantity + quantity if not created else quantity
    item.save()

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


# cart/views.py — add this function
def cart_data(request):
    from django.http import JsonResponse
    cart  = get_or_create_cart(request)
    items = []
    for item in cart.items.select_related('product').prefetch_related('product__images','product__vendor').all():
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
    return JsonResponse({'count': cart.total_items, 'total': str(cart.total_price), 'items': items})


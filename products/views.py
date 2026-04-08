# products/views.py
from django.shortcuts import render, get_object_or_404
from django.db.models import Q
from .models import Product, Category
from cart.models import Cart, CartItem


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


def product_list(request):
    products   = Product.objects.filter(status='active').prefetch_related('images')
    categories = Category.objects.filter(is_active=True)
    cart       = get_or_create_cart(request)

    category_slug = request.GET.get('category')
    search_query  = request.GET.get('q', '').strip()
    sort_by       = request.GET.get('sort', 'newest')

    if category_slug:
        products = products.filter(category__slug=category_slug)

    if search_query:
        products = products.filter(
            Q(name__icontains=search_query) |
            Q(description__icontains=search_query) |
            Q(category__name__icontains=search_query)
        )

    sort_map = {
        'newest':     '-created_at',
        'price_low':  'selling_price',
        'price_high': '-selling_price',
        'name':       'name',
    }
    products = products.order_by(sort_map.get(sort_by, '-created_at'))
    featured = Product.objects.filter(
        status='active', is_featured=True
    ).prefetch_related('images')[:4]

    return render(request, 'products/product_list.html', {
        'products':        products,
        'categories':      categories,
        'featured':        featured,
        'cart_count':      cart.total_items,
        'active_category': category_slug,
        'search_query':    search_query,
        'sort_by':         sort_by,
    })


def product_detail(request, slug):
    product = get_object_or_404(Product, slug=slug, status='active')
    cart    = get_or_create_cart(request)
    related = Product.objects.filter(
        category=product.category, status='active'
    ).exclude(pk=product.pk)[:4]

    return render(request, 'products/product_detail.html', {
        'product':    product,
        'images':     product.images.all(),
        'related':    related,
        'in_cart':    cart.items.filter(product=product).exists(),
        'cart_count': cart.total_items,
    })
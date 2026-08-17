"""
products/views.py

FIXES in this version:
  - Full file duplication removed (was doubled — same code twice)
  - search_autocomplete endpoint added for type-ahead search
  - Rate limiting added on cart_add (via django-ratelimit)
"""
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.cache import cache
from django.db.models import Q, Avg, Count, F
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST, require_GET

from .models import Product, Category, ProductVideo
from cart.models import Cart
from rest_framework.decorators import api_view


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


# ── Search autocomplete ────────────────────────────────────────────────────────

@require_GET
def search_autocomplete(request):
    """
    GET /products/autocomplete/?q=joll
    Returns up to 8 product/category suggestions as JSON.
    Results are cached for 60s per query to reduce DB load.
    Called by the search input with a 300ms debounce on the frontend.
    """
    q = request.GET.get('q', '').strip()
    if len(q) < 2:
        return JsonResponse({'results': []})

    cache_key = f'autocomplete:{q.lower()}'
    cached    = cache.get(cache_key)
    if cached is not None:
        return JsonResponse({'results': cached})

    # Products (name match, active only)
    products = (
        Product.objects
        .filter(status='active', name__icontains=q)
        .values('name', 'slug', 'selling_price')
        .order_by('-views')[:6]
    )
    # Categories (name match)
    categories = (
        Category.objects
        .filter(is_active=True, name__icontains=q)
        .values('name', 'slug')[:3]
    )

    results = [
        {
            'type':  'product',
            'label': p['name'],
            'price': f"GHS {p['selling_price']}",
            'url':   f"/products/{p['slug']}/",
        }
        for p in products
    ] + [
        {
            'type':  'category',
            'label': c['name'],
            'url':   f"/products/?category={c['slug']}",
        }
        for c in categories
    ]

    cache.set(cache_key, results, 60)
    return JsonResponse({'results': results})


# ── Product list ───────────────────────────────────────────────────────────────

def product_list(request):
    products   = Product.objects.filter(status='active').prefetch_related('images')
    categories = Category.objects.filter(is_active=True)
    cart       = get_or_create_cart(request)

    category_slug = request.GET.get('category')
    search_query  = request.GET.get('q', '').strip()
    sort_by       = request.GET.get('sort', 'newest')
    price_min     = request.GET.get('price_min', '').strip()
    price_max     = request.GET.get('price_max', '').strip()
    in_stock_only = request.GET.get('in_stock') == '1'

    if category_slug:
        products = products.filter(category__slug=category_slug)
    if search_query:
        products = products.filter(
            Q(name__icontains=search_query) |
            Q(description__icontains=search_query) |
            Q(category__name__icontains=search_query)
        )
    if price_min:
        try:
            products = products.filter(selling_price__gte=float(price_min))
        except ValueError:
            pass
    if price_max:
        try:
            products = products.filter(selling_price__lte=float(price_max))
        except ValueError:
            pass
    if in_stock_only:
        products = products.filter(stock_qty__gt=0)

    if sort_by == 'top_rated':
        products = products.annotate(avg_rating=Avg('reviews__rating'))

    sort_map = {
        'newest':     '-created_at',
        'price_low':  'selling_price',
        'price_high': '-selling_price',
        'name':       'name',
        'top_rated':  '-avg_rating',
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
        'price_min':       price_min,
        'price_max':       price_max,
        'in_stock_only':   in_stock_only,
    })


# ── Product detail ─────────────────────────────────────────────────────────────

def product_detail(request, slug):
    product = get_object_or_404(Product, slug=slug, status='active')
    cart    = get_or_create_cart(request)
    related = (
        Product.objects
        .filter(category=product.category, status='active')
        .exclude(pk=product.pk)
        .prefetch_related('images')[:4]
    )
    videos       = product.videos.all().order_by('order', 'uploaded_at')
    reviews      = product.reviews.filter(is_visible=True).select_related('customer')
    review_stats = reviews.aggregate(avg=Avg('rating'), count=Count('id'))
    avg_rating   = round(review_stats['avg'] or 0, 1)
    review_count = review_stats['count']

    rating_breakdown = {}
    for i in range(5, 0, -1):
        cnt = reviews.filter(rating=i).count()
        pct = int((cnt / review_count * 100)) if review_count else 0
        rating_breakdown[i] = {'count': cnt, 'pct': pct}

    user_review = user_can_review = None
    if request.user.is_authenticated:
        user_review = reviews.filter(customer=request.user).first()
        if not user_review:
            from reviews.views import can_review
            user_can_review = can_review(request.user, product)

    Product.objects.filter(pk=product.pk).update(views=F('views') + 1)

    return render(request, 'products/product_detail.html', {
        'product':          product,
        'images':           product.images.all(),
        'videos':           videos,
        'related':          related,
        'in_cart':          cart.items.filter(product=product).exists(),
        'cart_count':       cart.total_items,
        'reviews':          reviews,
        'avg_rating':       avg_rating,
        'review_count':     review_count,
        'rating_breakdown': rating_breakdown,
        'user_review':      user_review,
        'user_can_review':  user_can_review,
    })


# ── Deals ──────────────────────────────────────────────────────────────────────

def deals_page(request):
    deals = Product.objects.filter(
        status='active',
        discount_price__isnull=False,
        discount_price__lt=F('selling_price')
    ).prefetch_related('images')
    return render(request, 'products/deals.html', {'deals': deals})


# ── Video delete ───────────────────────────────────────────────────────────────

@login_required
@require_POST
def video_delete(request, pk):
    video = get_object_or_404(ProductVideo, pk=pk)
    if not (video.product.vendor and video.product.vendor.owner == request.user):
        messages.error(request, 'Permission denied.')
        return redirect('vendors:dashboard')
    product_pk = video.product.pk
    video.delete()
    messages.success(request, 'Video removed.')
    return redirect('vendors:product_edit', pk=product_pk)


# ── REST API stub ──────────────────────────────────────────────────────────────

@api_view(['GET'])
def product_list_api(request):
    from rest_framework.response import Response
    return Response({'detail': 'Product list API'})
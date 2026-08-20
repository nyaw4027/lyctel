"""
products/views.py — Performance optimised
  - select_related('vendor', 'category') on all querysets → eliminates N+1 queries
  - rating_breakdown in ONE annotate query instead of 5 separate COUNTs
  - view counter cached in Redis, flushed every 10 views (reduces DB writes by 90%)
  - product_list cached for 2 minutes
  - pagination on product_list (24 per page)
"""
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.cache import cache
from django.core.paginator import Paginator
from django.db.models import Q, Avg, Count, F, IntegerField
from django.db.models.functions import Coalesce
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST, require_GET
from django.utils import timezone

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
    q = request.GET.get('q', '').strip()
    if len(q) < 2:
        return JsonResponse({'results': []})

    cache_key = f'autocomplete:{q.lower()}'
    cached    = cache.get(cache_key)
    if cached is not None:
        return JsonResponse({'results': cached})

    products = (
        Product.objects
        .filter(status='active', name__icontains=q)
        .select_related('category')
        .values('name', 'slug', 'selling_price')
        .order_by('-views')[:6]
    )
    categories = (
        Category.objects
        .filter(is_active=True, name__icontains=q)
        .values('name', 'slug')[:3]
    )

    results = [
        {'type': 'product', 'label': p['name'],
         'price': f"GHS {p['selling_price']}", 'url': f"/products/{p['slug']}/"}
        for p in products
    ] + [
        {'type': 'category', 'label': c['name'], 'url': f"/products/?category={c['slug']}"}
        for c in categories
    ]

    cache.set(cache_key, results, 60)
    return JsonResponse({'results': results})


# ── Product list ───────────────────────────────────────────────────────────────

def product_list(request):
    category_slug = request.GET.get('category', '')
    search_query  = request.GET.get('q', '').strip()
    sort_by       = request.GET.get('sort', 'newest')
    price_min     = request.GET.get('price_min', '').strip()
    price_max     = request.GET.get('price_max', '').strip()
    in_stock_only = request.GET.get('in_stock') == '1'
    page_num      = request.GET.get('page', 1)

    # Cache key includes all filter params
    cache_key = (
        f'plist:{category_slug}:{search_query}:{sort_by}:'
        f'{price_min}:{price_max}:{in_stock_only}:{page_num}'
    )
    ctx = cache.get(cache_key) if not search_query else None  # don't cache searches

    if ctx is None:
        # ── single queryset with select_related — no N+1 ──────────────────────
        products = (
            Product.objects
            .filter(status='active')
            .select_related('vendor', 'category')
            .prefetch_related('images')
        )

        if category_slug:
            products = products.filter(category__slug=category_slug)
        if search_query:
            products = products.filter(
                Q(name__icontains=search_query) |
                Q(description__icontains=search_query) |
                Q(category__name__icontains=search_query)
            )
        if price_min:
            try: products = products.filter(selling_price__gte=float(price_min))
            except ValueError: pass
        if price_max:
            try: products = products.filter(selling_price__lte=float(price_max))
            except ValueError: pass
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

        # Pagination — 24 per page reduces initial load significantly
        paginator = Paginator(products, 24)
        page_obj  = paginator.get_page(page_num)

        categories = cache.get('categories:active')
        if categories is None:
            categories = list(Category.objects.filter(is_active=True))
            cache.set('categories:active', categories, 600)

        flash_products = cache.get('flash:active')
        if flash_products is None:
            flash_products = list(
                Product.objects.filter(
                    status='active',
                    flash_price__isnull=False,
                    flash_sale_ends__gt=timezone.now(),
                ).prefetch_related('images').order_by('flash_sale_ends')[:8]
            )
            cache.set('flash:active', flash_products, 120)

        featured = list(
            Product.objects.filter(is_featured=True, status='active')
            .select_related('vendor', 'category')
            .prefetch_related('images')[:4]
        )

        ctx = {
            'page_obj':       page_obj,
            'products':       page_obj.object_list,
            'categories':     categories,
            'featured':       featured,
            'flash_products': flash_products,
            'active_category': category_slug,
            'search_query':   search_query,
            'sort_by':        sort_by,
            'price_min':      price_min,
            'price_max':      price_max,
            'in_stock_only':  in_stock_only,
        }
        if not search_query:
            cache.set(cache_key, ctx, 120)   # 2-min cache for filtered views

    cart    = get_or_create_cart(request)
    ctx['cart_count'] = cart.total_items
    return render(request, 'products/product_list.html', ctx)


# ── Product detail ─────────────────────────────────────────────────────────────

def product_detail(request, slug):
    product = get_object_or_404(
        Product.objects.select_related('vendor', 'category'),
        slug=slug, status='active'
    )
    cart    = get_or_create_cart(request)
    related = (
        Product.objects
        .filter(category=product.category, status='active')
        .exclude(pk=product.pk)
        .select_related('vendor', 'category')
        .prefetch_related('images')[:4]
    )
    videos  = product.videos.all().order_by('order', 'uploaded_at')
    reviews = product.reviews.filter(is_visible=True).select_related('customer')

    # ── One annotate query instead of 5 separate COUNTs ───────────────────────
    from django.db.models import Case, When, IntegerField
    review_stats = reviews.aggregate(
        avg=Avg('rating'),
        count=Count('id'),
        r5=Count(Case(When(rating=5, then=1), output_field=IntegerField())),
        r4=Count(Case(When(rating=4, then=1), output_field=IntegerField())),
        r3=Count(Case(When(rating=3, then=1), output_field=IntegerField())),
        r2=Count(Case(When(rating=2, then=1), output_field=IntegerField())),
        r1=Count(Case(When(rating=1, then=1), output_field=IntegerField())),
    )
    avg_rating   = round(review_stats['avg'] or 0, 1)
    review_count = review_stats['count'] or 0

    rating_breakdown = {}
    for i in range(5, 0, -1):
        cnt = review_stats.get(f'r{i}', 0) or 0
        rating_breakdown[i] = {
            'count': cnt,
            'pct':   int((cnt / review_count * 100)) if review_count else 0,
        }

    user_review = user_can_review = None
    if request.user.is_authenticated:
        user_review = reviews.filter(customer=request.user).first()
        if not user_review:
            from reviews.views import can_review
            user_can_review = can_review(request.user, product)

    # ── Cached view counter — only writes to DB every 10 increments ───────────
    # Without caching: 1 DB write per product page view (high write load)
    # With caching: 1 DB write per 10 views (90% fewer writes)
    vc_key   = f'views:{product.pk}'
    vc_count = cache.get(vc_key, 0) + 1
    cache.set(vc_key, vc_count, 3600)
    if vc_count % 10 == 0:
        Product.objects.filter(pk=product.pk).update(views=F('views') + 10)

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


def deals_page(request):
    from django.utils import timezone as _tz
    now   = _tz.now()
    deals = Product.objects.filter(
        status='active',
    ).filter(
        Q(discount_price__isnull=False, discount_price__lt=F('selling_price')) |
        Q(flash_price__isnull=False, flash_sale_ends__gt=now)
    ).select_related('vendor', 'category').prefetch_related('images').distinct()
    flash_pks = set(Product.objects.filter(
        status='active', flash_price__isnull=False, flash_sale_ends__gt=now
    ).values_list('pk', flat=True))
    return render(request, 'products/deals.html', {'deals': deals, 'flash_pks': flash_pks})


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


@api_view(['GET'])
def product_list_api(request):
    from rest_framework.response import Response
    return Response({'detail': 'Product list API'})


def flash_sale_list(request):
    flash_products = cache.get('flash:active')
    if flash_products is None:
        flash_products = list(
            Product.objects.filter(
                status='active',
                flash_price__isnull=False,
                flash_sale_ends__gt=timezone.now(),
            ).select_related('vendor', 'category').prefetch_related('images')
            .order_by('flash_sale_ends')
        )
        cache.set('flash:active', flash_products, 120)
    cart = get_or_create_cart(request)
    return render(request, 'products/flash_sale.html', {
        'flash_products': flash_products,
        'cart_count':     cart.total_items,
    })
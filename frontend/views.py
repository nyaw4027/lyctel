from django.shortcuts import render
from django.core.cache import cache
from django.db.models import Sum
from products.models import Product, Category, ProductVideo
from order.models import OrderItem


def _cart_count(request):
    if request.user.is_authenticated:
        try:
            return request.user.cart.total_items
        except Exception:
            pass
    return 0


def home(request):
    # ── Cache heavy queries for 5 minutes ─────────────────────────────────────
    # The home page runs 6 queries including an expensive OrderItem aggregation.
    # Caching reduces DB load from ~6 queries/request to ~1 (just cart count).
    CACHE_TTL = 300   # 5 minutes — fast enough to show new products

    hot_products = cache.get('home:hot_products')
    if hot_products is None:
        valid_products = Product.objects.filter(status='active').exclude(
            slug__isnull=True).exclude(slug='')

        top_ids = list(
            OrderItem.objects
            .filter(order__payment_status='paid', product__isnull=False)
            .values('product')
            .annotate(total_sold=Sum('quantity'))
            .order_by('-total_sold')
            .values_list('product', flat=True)[:4]
        )
        top_map      = {p.pk: p for p in valid_products.filter(
            pk__in=top_ids).prefetch_related('images').select_related('vendor', 'category')}
        hot_products = [top_map[pk] for pk in top_ids if pk in top_map]

        if len(hot_products) < 4:
            fallback = list(
                valid_products
                .exclude(pk__in=[p.pk for p in hot_products])
                .prefetch_related('images').select_related('vendor', 'category')
                .order_by('-is_featured', '-created_at')
                [:4 - len(hot_products)]
            )
            hot_products = hot_products + fallback

        cache.set('home:hot_products', hot_products, CACHE_TTL)

    featured = cache.get('home:featured')
    if featured is None:
        featured = list(
            Product.objects.filter(is_featured=True, status='active')
            .prefetch_related('images').select_related('vendor', 'category')[:4]
        )
        cache.set('home:featured', featured, CACHE_TTL)

    new_products = cache.get('home:new_products')
    if new_products is None:
        new_products = list(
            Product.objects.filter(status='active')
            .prefetch_related('images', 'videos').select_related('vendor', 'category')
            .order_by('-created_at')[:10]
        )
        cache.set('home:new_products', new_products, CACHE_TTL)

    categories = cache.get('home:categories')
    if categories is None:
        categories = list(Category.objects.filter(is_active=True))
        cache.set('home:categories', categories, CACHE_TTL)

    product_videos = cache.get('home:product_videos')
    if product_videos is None:
        product_videos = list(
            ProductVideo.objects
            .select_related('product', 'product__vendor')
            .filter(product__status='active')
            .exclude(product__slug__isnull=True)
            .exclude(product__slug='')
            .order_by('order', '-uploaded_at')[:12]
        )
        cache.set('home:product_videos', product_videos, CACHE_TTL)

    return render(request, 'frontend/home.html', {
        'hot_products':   hot_products,
        'featured':       featured,
        'new_products':   new_products,
        'categories':     categories,
        'product_videos': product_videos,
        'cart_count':     _cart_count(request),
    })


def about(request):
    try:
        from .models import AboutPage
        page = AboutPage.objects.prefetch_related('stats', 'features', 'team').first()
    except Exception:
        page = None
    return render(request, 'frontend/about.html', {
        'page':         page,
        'stats':        page.stats.all()                 if page else [],
        'features':     page.features.all()              if page else [],
        'team_members': page.team.filter(is_active=True) if page else [],
        'cart_count':   _cart_count(request),
    })


def contact(request):
    return render(request, 'frontend/contact.html', {'cart_count': _cart_count(request)})

def how_it_works(request):
    return render(request, 'frontend/how_it_works.html', {'cart_count': _cart_count(request)})

def privacy_policy(request):
    return render(request, 'frontend/privacy_policy.html', {'cart_count': _cart_count(request)})

def terms(request):
    return render(request, 'frontend/terms.html', {'cart_count': _cart_count(request)})

def cookies(request):
    return render(request, 'frontend/cookies.html', {'cart_count': _cart_count(request)})
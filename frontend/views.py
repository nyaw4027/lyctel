from django.shortcuts import render
from django.db.models import Sum
from products.models import Product, Category, ProductVideo
from order.models import OrderItem


# ── HELPER ────────────────────────────────────────────────

def _cart_count(request):
    if request.user.is_authenticated:
        try:
            return request.user.cart.total_items
        except Exception:
            pass
    return 0


# ── HOME ──────────────────────────────────────────────────

def home(request):
    valid_products = Product.objects.exclude(slug__isnull=True).exclude(slug='')

    # Top 4 most-purchased products (paid orders only)
    # NOTE: evaluating the queryset with list() before slicing avoids a subquery
    # that can silently drop the ORDER BY in some databases when used as __in lookup.
    top_ids = list(
        OrderItem.objects
        .filter(order__payment_status='paid', product__isnull=False)
        .values('product')
        .annotate(total_sold=Sum('quantity'))
        .order_by('-total_sold')
        .values_list('product', flat=True)[:4]
    )

    top_map      = {p.pk: p for p in valid_products.filter(pk__in=top_ids, status='active').prefetch_related('images')}
    hot_products = [top_map[pk] for pk in top_ids if pk in top_map]

    if len(hot_products) < 4:
        fallback = (
            valid_products
            .filter(status='active')
            .exclude(pk__in=[p.pk for p in hot_products])
            .prefetch_related('images')
            .order_by('-is_featured', '-created_at')
            [:4 - len(hot_products)]
        )
        hot_products = hot_products + list(fallback)

    featured     = valid_products.filter(is_featured=True, status='active').prefetch_related('images')[:4]
    new_products = valid_products.filter(status='active').prefetch_related('images').order_by('-created_at')[:10]
    categories   = Category.objects.filter(is_active=True)

    # Videos from active products, respecting vendor-set order
    product_videos = (
        ProductVideo.objects
        .select_related('product', 'product__vendor')
        .filter(product__status='active')
        .exclude(product__slug__isnull=True)
        .exclude(product__slug='')
        .order_by('order', '-uploaded_at')[:12]
    )

    return render(request, 'frontend/home.html', {
        'hot_products':   hot_products,
        'featured':       featured,
        'new_products':   new_products,
        'categories':     categories,
        'product_videos': product_videos,
        'cart_count':     _cart_count(request),
    })


# ── ABOUT ─────────────────────────────────────────────────

def about(request):
    """
    Gracefully handles a missing AboutPage table (e.g. migrations not yet run)
    so it never crashes with a 500.
    """
    try:
        from .models import AboutPage
        page = AboutPage.objects.prefetch_related('stats', 'features', 'team').first()
    except Exception:
        page = None

    return render(request, 'frontend/about.html', {
        'page':         page,
        'stats':        page.stats.all()                  if page else [],
        'features':     page.features.all()               if page else [],
        'team_members': page.team.filter(is_active=True)  if page else [],
        'cart_count':   _cart_count(request),
    })


# ── STATIC PAGES ──────────────────────────────────────────

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
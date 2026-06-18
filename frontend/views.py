from django.shortcuts import render
from django.db.models import Sum
from products.models import Product, Category
from order.models import OrderItem


def home(request):
    valid_products = Product.objects.exclude(slug__isnull=True).exclude(slug='')

    # Top 4 most purchased products
    top_ids = (
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

    return render(request, 'frontend/home.html', {
        'hot_products': hot_products,
        'featured':     featured,
        'new_products': new_products,
        'categories':   categories,
        'cart_count':   0,
    })


def about(request):
    """
    About page — gracefully handles missing AboutPage table
    (e.g. migrations not yet run) so it never crashes with a 500.
    """
    try:
        from .models import AboutPage
        page = AboutPage.objects.prefetch_related('stats', 'features', 'team').first()
    except Exception:
        page = None

    return render(request, 'frontend/about.html', {
        'page':         page,
        'stats':        page.stats.all()    if page else [],
        'features':     page.features.all() if page else [],
        'team_members': page.team.filter(is_active=True) if page else [],
        'cart_count':   0,
    })


def contact(request):
    return render(request, 'frontend/contact.html', {'cart_count': 0})


def how_it_works(request):
    return render(request, 'frontend/how_it_works.html', {'cart_count': 0})


def privacy_policy(request):
    return render(request, 'frontend/privacy_policy.html', {'cart_count': 0})


def terms(request):
    return render(request, 'frontend/terms.html', {'cart_count': 0})


def cookies(request):
    return render(request, 'frontend/cookies.html', {'cart_count': 0})
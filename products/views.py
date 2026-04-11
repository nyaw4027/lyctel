from django.shortcuts import render, get_object_or_404
from django.db.models import Q, Avg, Count
from .models import Product, Category
from cart.models import Cart


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
    })


def product_detail(request, slug):
    product = get_object_or_404(Product, slug=slug, status='active')
    cart    = get_or_create_cart(request)
    related = Product.objects.filter(
        category=product.category, status='active'
    ).exclude(pk=product.pk)[:4]

    # Reviews & stats
    reviews      = product.reviews.filter(is_visible=True).select_related('customer')
    review_stats = reviews.aggregate(avg=Avg('rating'), count=Count('id'))
    avg_rating   = round(review_stats['avg'] or 0, 1)
    review_count = review_stats['count']

    # Per-star breakdown
    rating_breakdown = {}
    for i in range(5, 0, -1):
        cnt = reviews.filter(rating=i).count()
        pct = int((cnt / review_count * 100)) if review_count else 0
        rating_breakdown[i] = {'count': cnt, 'pct': pct}

    # Current user review status
    user_review     = None
    user_can_review = False
    if request.user.is_authenticated:
        user_review = reviews.filter(customer=request.user).first()
        if not user_review:
            from reviews.views import can_review
            user_can_review = can_review(request.user, product)

    return render(request, 'products/product_detail.html', {
        'product':          product,
        'images':           product.images.all(),
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
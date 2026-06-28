from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Q, Avg, Count, F
from django.http import JsonResponse
from django.views.decorators.http import require_POST

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
    ).exclude(pk=product.pk).prefetch_related('images')[:4]

    # Videos
    videos = product.videos.all().order_by('order', 'uploaded_at')

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

    # Increment view count
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


def deals_page(request):
    # FIXED: previously had no status filter at all, so hidden and
    # out-of-stock products with a discount_price could still show up on
    # the public Deals page.
    deals = Product.objects.filter(
        status='active',
        discount_price__isnull=False,
        discount_price__lt=F("selling_price")
    ).prefetch_related('images')

    return render(request, "products/deals.html", {
        "deals": deals
    })


# ── VIDEO DELETE (vendor only) ─────────────────────────────
@login_required
@require_POST
def video_delete(request, pk):
    """Vendor deletes one of their product videos."""
    video = get_object_or_404(ProductVideo, pk=pk)

    # FIXED: `if video.product.vendor and video.product.vendor.owner != request.user`
    # short-circuited to a falsy `None` whenever the product had no vendor at
    # all, which SKIPPED the permission check entirely — letting any logged-in
    # user delete that video. The check now explicitly requires a vendor AND
    # ownership before allowing the delete.
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
    products = Product.objects.all()
    # Serializer would go here
    return Response({'detail': 'Product list API'})
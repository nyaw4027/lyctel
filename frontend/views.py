from django.shortcuts import render
from products.models import Product, Category


def home(request):
    valid_products = Product.objects.exclude(slug__isnull=True).exclude(slug="")

    featured = valid_products.filter(
        is_featured=True,
        status='active'
    )[:4]

    new_products = valid_products.filter(
        status='active'
    ).order_by('-created_at')[:10]

    categories = Category.objects.filter(is_active=True)

    return render(request, 'frontend/home.html', {
        'featured': featured,
        'new_products': new_products,
        'categories': categories,
        'cart_count': 0,
    })
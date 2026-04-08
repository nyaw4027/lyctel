from django.shortcuts import render
from products.models import Product, Category


def home(request):
    featured = Product.objects.filter(is_featured=True, status='active').exclude(id__isnull=True)[:4]
    new_products = Product.objects.filter(status='active').exclude(id__isnull=True).order_by('-created_at')[:10]
    categories = Category.objects.filter(is_active=True)

    return render(request, 'frontend/home.html', {
        'featured': featured,
        'new_products': new_products,
        'categories': categories,
        'cart_count': 0,
    })
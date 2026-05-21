from django.shortcuts import render
from products.models import Product, Category
from .models import AboutPage


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

def about(request):
    page = AboutPage.objects.prefetch_related("stats", "features", "team").first()
    
    # If the database table is completely empty, pass empty lists so the template doesn't crash
    context = {
        "page": page,
        "stats": page.stats.all() if page else [],
        "features": page.features.all() if page else [],
        "team": page.team.all() if page else [],
    }

    return render(request, "frontend/about.html", context)


def contact(request):
    return render(request, "frontend/contact.html")


   

def how_it_works(request):
    return render(request, 'frontend/how_it_works.html')


def privacy_policy(request):
    return render(request, 'frontend/privacy_policy.html')


def terms(request):
    return render(request, 'frontend/terms.html')


def cookies(request):
    return render(request, 'frontend/cookies.html')


# ecommerce/urls.py
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('frontend.urls')),  # homepage
    path('products/', include('products.urls', namespace='products')),
    path('cart/', include('cart.urls')), 
    path('accounts/',  include('accounts.urls')),
    path('orders/', include('order.urls', namespace='order')),
    path('dashboard/', include('dashboard.urls')),
    path('rider/', include('rider.urls')),
    path('', include('reviews.urls')),
    path('', include('vendors.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
# ecommerce/urls.py
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
urlpatterns = [
    path('admin/', admin.site.urls),
    path("api/auth/login/", TokenObtainPairView.as_view()),
    path("api/auth/refresh/", TokenRefreshView.as_view()),
    path('', include('frontend.urls')),
    path('products/', include('products.urls')),
    path('cart/', include('cart.urls')),
    path('accounts/', include('accounts.urls')),
    path('orders/', include('order.urls', namespace='order')),
    path('checkout/', include('payment.urls')),   # ← ADD THIS
    path('dashboard/', include('dashboard.urls')),
    path('rider/', include('rider.urls')),
    path('', include('reviews.urls')),
    path('', include('vendors.urls')),
    path('delivery/', include(('delivery.urls', 'delivery'), namespace='delivery')),
    path("api/order/", include("order.api.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
from django.contrib import admin
from django.urls import include, path, re_path
from django.conf import settings
from django.conf.urls.static import static
from django.views.static import serve
from ecommerce import push_views
from ecommerce.pwa_views import (
    service_worker,
    web_manifest,
    offline_page,
)

urlpatterns = [
    # Admin
    path('admin/', admin.site.urls),

    # Main site
    path('', include('frontend.urls')),

    # Apps
    path('food/',      include(('food.urls',     'food'),     namespace='food')),
    path('products/',  include('products.urls')),
    path('cart/',      include('cart.urls')),
    path('accounts/',  include('accounts.urls')),
    path('orders/',    include(('order.urls',    'order'),    namespace='order')),
    path('checkout/',  include('payment.urls')),
    path('dashboard/', include('dashboard.urls')),
    path('rider/',     include('rider.urls')),
    path('delivery/',  include(('delivery.urls', 'delivery'), namespace='delivery')),

    # APIs
    path('api/order/', include('order.api.urls')),

    # Reviews & Vendors
    path('', include('reviews.urls')),
    path('', include('vendors.urls')),

    # PWA
    path('sw.js',         service_worker, name='service-worker'),
    path('manifest.json', web_manifest,   name='web-manifest'),
    path('offline/',      offline_page,   name='offline'),

    path('chat/', include('chat.urls')),

   
# Inside urlpatterns list:
    path('push/subscribe/',   push_views.save_push_subscription,   name='push_subscribe'),
    path('push/unsubscribe/', push_views.delete_push_subscription, name='push_unsubscribe'),
]



# Static files in local development only
if settings.DEBUG:
    urlpatterns += static(
        settings.STATIC_URL,
        document_root=settings.STATIC_ROOT,
    )
from django.contrib import admin
from django.urls import include, path
from django.conf import settings
from django.conf.urls.static import static
from django.http import JsonResponse
from django.db import connection
from ecommerce import push_views
from ecommerce.pwa_views import service_worker, web_manifest, offline_page


def health_check(request):
    """
    /health/ — Railway health check + uptime monitoring.
    Set Railway Health Check Path to /health/
    """
    data = {'status': 'ok'}
    try:
        connection.ensure_connection()
        data['db'] = 'ok'
    except Exception as e:
        data['db'] = f'error: {e}'
        return JsonResponse(data, status=503)
    try:
        from django.core.cache import cache
        cache.set('_hc', '1', 5)
        data['cache'] = 'ok' if cache.get('_hc') else 'miss'
    except Exception:
        data['cache'] = 'unavailable'
    return JsonResponse(data)


urlpatterns = [
    path('health/',     health_check,  name='health'),
    path('admin/',      admin.site.urls),
    path('',            include('frontend.urls')),
    path('food/',       include(('food.urls',       'food'),       namespace='food')),
    path('products/',   include('products.urls')),
    path('cart/',       include('cart.urls')),
    path('accounts/',   include('accounts.urls')),
    path('orders/',     include(('order.urls',      'order'),      namespace='order')),
    path('checkout/',   include(('payment.urls',    'payment'),    namespace='payment')),
    path('dashboard/',  include('dashboard.urls')),
    path('rider/',      include('rider.urls')),
    path('delivery/',   include(('delivery.urls',   'delivery'),   namespace='delivery')),
    path('livestream/', include(('livestream.urls', 'livestream'), namespace='livestream')),
    path('fraud/',      include(('fraud.urls',      'fraud'),      namespace='fraud')),
    path('staff/',      include(('staff.urls',      'staff'),      namespace='staff')),
    path('api/order/',  include('order.api.urls')),
    path('',            include('reviews.urls')),
    path('',            include('vendors.urls')),
    path('sw.js',       service_worker, name='service-worker'),
    path('manifest.json', web_manifest, name='web-manifest'),
    path('offline/',    offline_page,  name='offline'),
    path('chat/',       include('chat.urls')),
    path('push/subscribe/',   push_views.save_push_subscription,   name='push_subscribe'),
    path('push/unsubscribe/', push_views.delete_push_subscription, name='push_unsubscribe'),
]

if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
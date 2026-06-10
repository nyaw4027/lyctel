
# ecommerce/urls.py

from django.contrib import admin
from django.urls import include, path
from django.conf import settings
from django.conf.urls.static import static

from ecommerce.pwa_views import (
    service_worker,
    web_manifest,
    offline_page,
)

urlpatterns = [
    # Admin
    path("admin/", admin.site.urls),

    # Main site
    path("", include("frontend.urls")),

    # Apps
    path("products/", include("products.urls")),
    path("cart/", include("cart.urls")),
    path("accounts/", include("accounts.urls")),
    path("orders/", include(("order.urls", "order"), namespace="order")),
    path("checkout/", include("payment.urls")),
    path("dashboard/", include("dashboard.urls")),
    path("rider/", include("rider.urls")),
    path("delivery/", include(("delivery.urls", "delivery"), namespace="delivery")),

    # APIs
    path("api/order/", include("order.api.urls")),

    # Reviews & Vendors
    path("", include("reviews.urls")),
    path("", include("vendors.urls")),

    # Progressive Web App (PWA)
    path("sw.js", service_worker, name="service-worker"),
    path("manifest.json", web_manifest, name="web-manifest"),
    path("offline/", offline_page, name="offline"),
]

# Media files (development)
if settings.DEBUG:
    urlpatterns += static(
        settings.MEDIA_URL,
        document_root=settings.MEDIA_ROOT
    )

    urlpatterns += static(
        settings.STATIC_URL,
        document_root=settings.STATIC_ROOT
    )


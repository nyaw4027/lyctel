from django.urls import path
from . import views

app_name = 'delivery'

urlpatterns = [
    # Customer-facing
    path('book/',                                   views.book_ride,             name='book_ride'),
    path('track/<str:order_ref>/',                  views.track_delivery,        name='track_delivery'),
    path('ride/<int:pk>/',                          views.track_ride,            name='track_ride'),

    # Data APIs
    path('data/<int:delivery_id>/',                 views.tracking_data,         name='tracking_data'),
    path('price/',                                  views.price_estimate,        name='price_estimate'),

    # Rider location + status (authenticated)
    path('location/<int:delivery_id>/update/',      views.update_rider_location, name='update_location'),
    path('status/<int:delivery_id>/<str:status>/',  views.update_delivery_status,name='update_status'),

    # Assignment
    path('assign/<int:delivery_id>/',               views.assign_nearest_rider,  name='assign_rider'),
    path('vendor-assign/<int:delivery_id>/<int:rider_id>/',
                                                    views.vendor_assign_rider,   name='vendor_assign'),

    # Rider dashboard (delivery app view)
    path('rider/',                                  views.rider_dashboard,       name='rider_dashboard'),

    # ── Acceptance timeout cron (item 5) ─────────────────────────────────────
    # Railway Cron: every minute → GET /delivery/timeout/
    # Header: X-Cron-Token: <CRON_TOKEN env var>
    path('timeout/',                                views.acceptance_timeout,    name='acceptance_timeout'),
]
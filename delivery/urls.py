from django.urls import path
from . import views

app_name = "delivery"

urlpatterns = [
    # Book a ride (customer / vendor)
    path("book/", views.book_ride, name="book_ride"),

    # Live tracking for standalone rides
    path("ride/<int:pk>/", views.track_ride, name="track_ride"),

    # Tracking (order-linked)
    path("track/<str:order_ref>/", views.track_delivery, name="track_delivery"),
    path("tracking-data/<int:delivery_id>/", views.tracking_data, name="tracking_data"),

    # Rider location push
    path("update-location/<int:delivery_id>/", views.update_rider_location, name="update_location"),

    # Status update
    path("update-status/<int:delivery_id>/<str:status>/", views.update_delivery_status, name="update_status"),

    # Auto-assign nearest rider
    path("assign/<int:delivery_id>/", views.assign_nearest_rider, name="assign_rider"),

    # Vendor manually assigns a specific rider
    path("vendor-assign/<int:delivery_id>/<int:rider_id>/", views.vendor_assign_rider, name="vendor_assign"),

    # Rider dashboard (legacy delivery app view)
    path("rider/dashboard/", views.rider_dashboard, name="rider_dashboard"),
]
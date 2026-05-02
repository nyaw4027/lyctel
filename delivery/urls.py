from django.urls import path
from . import views

app_name = "delivery"

urlpatterns = [
    # Tracking
    path("track/<str:order_ref>/", views.track_delivery, name="track_delivery"),
    path("tracking-data/<int:delivery_id>/", views.tracking_data, name="tracking_data"),

    # Rider location
    path("update-location/<int:delivery_id>/", views.update_rider_location, name="update_location"),

    # Status update
    path("update-status/<int:delivery_id>/<str:status>/", views.update_delivery_status, name="update_status"),

    # Assign rider
    path("assign/<int:delivery_id>/", views.assign_nearest_rider, name="assign_rider"),

    # Rider dashboard
    path("rider/dashboard/", views.rider_dashboard, name="rider_dashboard"),
]
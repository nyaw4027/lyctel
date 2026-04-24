from django.urls import path
from . import views
from .views import update_rider_location,assign_nearest_rider

app_name = "delivery"

urlpatterns = [
    path("track/<int:order_id>/", views.track_delivery, name="track"),
    path("update/<int:delivery_id>/<str:status>/", views.update_delivery_status, name="update_status"),
    path("location/<int:delivery_id>/", views.update_rider_location, name="update_location"),
    path("tracking-data/<int:delivery_id>/", views.tracking_data, name="tracking_data"),
    path("update-location/<int:delivery_id>/", update_rider_location, name="update_location"),
    path("assign/<int:delivery_id>/", assign_nearest_rider, name="assign_rider"),
    path("rider/dashboard/", views.rider_dashboard, name="rider_dashboard"),
    path("track/<str:order_ref>/", views.track_delivery, name="track_delivery"),
    path("update-location/<int:pk>/", views.update_rider_location, name="update_location"),
    path("tracking/<int:pk>/", views.tracking_data, name="tracking_data")
   
    
   
    
]
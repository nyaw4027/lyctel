from django.urls import path
from . import views

app_name = 'rider'

urlpatterns = [
    # Dashboard
    path('',                              views.dashboard,         name='dashboard'),
    path('toggle/',                       views.toggle_status,     name='toggle_status'),

    # Accept / Reject
    path('accept/<int:pk>/',              views.accept_delivery,   name='accept'),
    path('reject/<int:pk>/',              views.reject_delivery,   name='reject'),

    # Live map
    path('map/<int:pk>/',                 views.live_map,          name='live_map'),

    # Delivery status
    path('delivery/<int:pk>/update/',     views.update_delivery,   name='update_delivery'),

    # GPS tracking
    path('location/update/',              views.update_location,   name='update_location'),
    path('location/<str:delivery_id>/',   views.rider_location_api, name='location_api'),
    path('eta/', views.eta_api, name='eta_api'),

    # Notifications
    path('notifications/<int:pk>/read/',  views.notification_read,     name='notif_read'),
    path('notifications/read-all/',       views.notification_read_all, name='notif_read_all'),
    path('notifications/count/',          views.notification_count,    name='notif_count'),
]
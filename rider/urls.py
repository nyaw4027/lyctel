from django.urls import path
from . import views

app_name = 'rider'

urlpatterns = [
    path('',                           views.dashboard,       name='dashboard'),
    path('toggle-status/',             views.toggle_status,   name='toggle_status'),
    path('delivery/<int:pk>/',         views.delivery_detail, name='delivery_detail'),
    path('delivery/<int:pk>/update/',  views.update_delivery, name='update_delivery'),
]
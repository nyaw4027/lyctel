from django.urls import path
from . import views

app_name = 'order'

urlpatterns = [
    path('checkout/',                           views.checkout,           name='checkout'),
    path('orders/',                             views.order_history,      name='history'),
    path('orders/<str:order_ref>/confirm/',     views.order_confirmation, name='confirmation'),
   
]
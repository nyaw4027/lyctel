from django.urls import path
from .views import my_orders

urlpatterns = [
    path("my-orders/", my_orders),
]
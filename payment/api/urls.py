from django.urls import path
from .views import my_payments

urlpatterns = [
    path("my-payments/", my_payments),
]
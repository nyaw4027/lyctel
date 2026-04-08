from django.urls import path
from . import views

app_name = 'payment'

urlpatterns = [
    path('checkout/payment/',                    views.payment_page,         name='page'),
    path('checkout/payment/callback/',           views.payment_callback,     name='callback'),
    path('checkout/payment/webhook/flutterwave/', views.flutterwave_webhook, name='flw_webhook'),
]
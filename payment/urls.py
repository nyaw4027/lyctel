from django.urls import path
from . import views

app_name = 'payment'

urlpatterns = [
    path('payment/',                    views.payment_page,        name='page'),
    path('payment/callback/',           views.payment_callback,    name='callback'),
    path('payment/webhook/flutterwave/', views.flutterwave_webhook, name='flutterwave_webhook'),
]
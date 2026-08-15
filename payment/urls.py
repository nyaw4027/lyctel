from django.urls import path
from . import views

app_name = 'payment'

urlpatterns = [
    # Step 2 of checkout — payment method selection
    path('pay/',                           views.payment_page,            name='page'),

    # Hubtel
    path('hubtel/init/<int:order_pk>/',    views.hubtel_init,             name='hubtel_init'),
    path('hubtel/callback/',               views.hubtel_callback,         name='hubtel_callback'),
    path('hubtel/cancel/',                 views.hubtel_cancel,           name='hubtel_cancel'),
    path('hubtel/webhook/',                views.hubtel_webhook,          name='hubtel_webhook'),
    # Lightweight JSON poll endpoint — used by payment/processing.html
    path('hubtel/status/<str:order_ref>/', views.hubtel_payment_status,  name='hubtel_status'),

    # Flutterwave
    path('flutterwave/init/<int:order_pk>/', views.flutterwave_init,       name='flutterwave_init'),
    path('flutterwave/callback/',            views.payment_callback,        name='callback'),
    path('flutterwave/webhook/',             views.flutterwave_webhook,     name='flutterwave_webhook'),
]
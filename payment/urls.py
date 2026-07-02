from django.urls import path
from . import views

app_name = 'payment'

urlpatterns = [
    # Step 2: payment method selection (redirected here from order:checkout)
    path('',                                        views.payment_page,        name='page'),

    # Paystack inline flow
    path('paystack/init/<int:order_pk>/',           views.paystack_init,       name='paystack_init'),
    path('paystack/verify/<int:order_pk>/',         views.paystack_verify,     name='paystack_verify'),
    path('paystack/callback/<str:tx_ref>/',         views.paystack_callback,   name='paystack-callback'),
    path('callback/',                       views.payment_callback,   name='callback'),
    path('flutterwave/init/<int:order_pk>/', views.flutterwave_init,   name='flutterwave_init'),

    # Webhooks
    path('webhook/paystack/',                       views.paystack_webhook,    name='paystack-webhook'),
    path('webhook/flutterwave/',                    views.flutterwave_webhook, name='flw-webhook'),
]
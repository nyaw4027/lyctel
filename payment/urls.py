from django.urls import path
from . import views

app_name = 'payment'

urlpatterns = [
    # ── Existing Flutterwave ──────────────────────────────
    path('',                        views.payment_page,        name='page'),
    path('callback/',               views.payment_callback,    name='callback'),
    path('webhook/flutterwave/',    views.flutterwave_webhook, name='flw-webhook'),

    # ── New Paystack ──────────────────────────────────────
    path('paystack/callback/<str:tx_ref>/', views.paystack_callback, name='paystack-callback'),
    path('webhook/paystack/',               views.paystack_webhook,  name='paystack-webhook'),
]
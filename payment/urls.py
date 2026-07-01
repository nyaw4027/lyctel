from django.urls import path
from . import views

app_name = 'payment'

urlpatterns = [
    # ── Checkout (new distance-based) ─────────────────────
    path('checkout/',               views.checkout,            name='checkout'),

    # ── Flutterwave ───────────────────────────────────────
    path('',                        views.payment_page,        name='page'),
    path('callback/',               views.payment_callback,    name='callback'),
    path('webhook/flutterwave/',    views.flutterwave_webhook, name='flw-webhook'),

    # ── Paystack ──────────────────────────────────────────
    path('paystack/init/<int:order_pk>/',           views.paystack_init,     name='paystack_init'),
    path('paystack/verify/<int:order_pk>/',         views.paystack_verify,   name='paystack_verify'),
    path('paystack/callback/<str:tx_ref>/',         views.paystack_callback, name='paystack-callback'),
    path('webhook/paystack/',                       views.paystack_webhook,  name='paystack-webhook'),
]
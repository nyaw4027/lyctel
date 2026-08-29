from django.urls import path
from . import views

app_name = 'payment'

urlpatterns = [
    # ── Step 2: Order review + pay button ─────────────────────────────────────
    path('pay/',                           views.payment_page,           name='page'),
    # Alias so failed.html "Try Again" works: payment:initiate <order_ref>
    path('initiate/<str:order_ref>/',      views.payment_initiate,       name='initiate'),

    # ── Hubtel Checkout ────────────────────────────────────────────────────────
    path('hubtel/init/<int:order_pk>/',    views.hubtel_init,            name='hubtel_init'),
    path('hubtel/callback/',              views.hubtel_callback,         name='hubtel_callback'),
    path('hubtel/cancel/',                views.hubtel_cancel,           name='hubtel_cancel'),
    path('hubtel/webhook/',               views.hubtel_webhook,          name='hubtel_webhook'),
    path('hubtel/status/<str:order_ref>/',views.hubtel_payment_status,   name='hubtel_status'),

    # ── Processing + Failed pages ──────────────────────────────────────────────
    # pay.html postMessage redirects here: payment:processing?order=<ref>
    path('processing/',                   views.payment_processing,      name='processing'),
    # pay.html redirects here on failure: payment:failed <order_ref>
    path('failed/<str:order_ref>/',       views.payment_failed,          name='failed'),

    # ── Flutterwave (legacy — kept for old callbacks) ─────────────────────────
    path('flutterwave/init/<int:order_pk>/', views.flutterwave_init,     name='flutterwave_init'),
    path('flutterwave/callback/',            views.payment_callback,     name='callback'),
    path('flutterwave/webhook/',             views.flutterwave_webhook,  name='flutterwave_webhook'),
]
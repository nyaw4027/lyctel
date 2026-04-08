
# ============================================================
# payment/urls.py
# ============================================================
 from django.urls import path
 from . import views

 app_name = 'payment'

 urlpatterns = [
     path('checkout/payment/',   views.payment_page,   name='page'),
     path('webhook/flutterwave/',views.flutterwave_webhook, name='flw_webhook'),
 ]
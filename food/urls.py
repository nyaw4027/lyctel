from django.urls import path
from . import views

app_name = 'food'

urlpatterns = [
    # ── Public ──────────────────────────────────────────────────────────
    path('',                                        views.food_home,                  name='home'),
    path('vendor/<slug:slug>/',                     views.vendor_menu,                name='menu'),

    # ── Restaurant registration & dashboard ──────────────────────────────
    path('register/',                               views.register_restaurant,        name='register'),
    path('dashboard/',                              views.restaurant_dashboard,       name='restaurant_dashboard'),
    path('dashboard/order/<str:ref>/update/',       views.restaurant_update_order,    name='restaurant_update_order'),
    path('dashboard/item/add/',                     views.restaurant_add_item,        name='restaurant_add_item'),
    path('dashboard/item/<int:pk>/edit/',           views.restaurant_edit_item,       name='restaurant_edit_item'),
    path('dashboard/item/<int:pk>/delete/',         views.restaurant_delete_item,     name='restaurant_delete_item'),
    path('dashboard/category/add/',                 views.restaurant_add_category,    name='restaurant_add_category'),
    path('dashboard/settings/',                     views.restaurant_settings,        name='restaurant_settings'),

    # ── Cart HTML page (FIX: was missing — food:cart was unresolvable) ───
    path('cart/',                                   views.cart_page,                  name='cart'),

    # ── Cart APIs ────────────────────────────────────────────────────────
    path('cart/add/<int:item_id>/',                 views.cart_add,                   name='cart_add'),
    path('cart/update/<int:item_id>/',              views.cart_update,                name='cart_update'),
    path('cart/clear/',                             views.cart_clear,                 name='cart_clear'),
    path('cart/data/',                              views.cart_data,                  name='cart_data'),

    # ── Pricing API ──────────────────────────────────────────────────────
    path('price-estimate/',                         views.price_estimate,             name='price_estimate'),

    # ── Checkout & orders ────────────────────────────────────────────────
    path('checkout/',                               views.checkout,                   name='checkout'),
    path('order/<str:ref>/',                        views.order_track,                name='order_track'),
    path('order/<str:ref>/api/',                    views.order_track_api,            name='order_track_api'),
    path('orders/',                                 views.order_history,              name='order_history'),
    path('orders/<str:ref>/reorder/',               views.reorder,                    name='reorder'),

    # ── Payment (Hubtel) ─────────────────────────────────────────────────
    # food_payment_initiate is called internally from checkout() — not a URL.
    # The three URLs below are needed for the Hubtel hosted checkout flow:
    #   callback → browser redirect after Hubtel checkout completes
    #   webhook  → Hubtel server-to-server payment confirmation (register
    #              this in the Hubtel dashboard:
    #              https://lynctel.up.railway.app/food/payment/webhook/)
    #   status   → AJAX poll endpoint used by food/payment_processing.html
    path('payment/callback/<str:tx_ref>/',          views.food_payment_callback,      name='payment_callback'),
    path('payment/webhook/',                        views.food_payment_webhook,       name='payment_webhook'),
    path('payment/status/<str:order_ref>/',         views.food_payment_status,        name='payment_status'),
]
from django.urls import path
from . import views

app_name = 'food'

urlpatterns = [
    # ── Public ────────────────────────────────────────────────────────────────
    path('',                                        views.food_home,               name='home'),
    path('debug/',                                  views.food_debug,              name='debug'),
    path('menu/<slug:slug>/',                       views.vendor_menu,             name='menu'),
    path('price/',                                  views.price_estimate,          name='price_estimate'),

    # ── Restaurant management ─────────────────────────────────────────────────
    path('register/',                               views.register_restaurant,     name='register'),
    path('restaurant/',                             views.restaurant_dashboard,    name='restaurant_dashboard'),
    path('restaurant/settings/',                    views.restaurant_settings,     name='restaurant_settings'),
    path('restaurant/order/<str:ref>/update/',      views.restaurant_update_order, name='restaurant_update_order'),
    path('restaurant/item/add/',                    views.restaurant_add_item,     name='restaurant_add_item'),
    path('restaurant/item/<int:pk>/edit/',          views.restaurant_edit_item,    name='restaurant_edit_item'),
    path('restaurant/item/<int:pk>/delete/',        views.restaurant_delete_item,  name='restaurant_delete_item'),
    path('restaurant/category/add/',                views.restaurant_add_category, name='restaurant_add_category'),

    # ── Cart ──────────────────────────────────────────────────────────────────
    path('cart/',                                   views.cart_page,               name='cart'),
    path('cart/add/<int:item_id>/',                 views.cart_add,                name='cart_add'),
    path('cart/update/<int:item_id>/',              views.cart_update,             name='cart_update'),
    path('cart/clear/',                             views.cart_clear,              name='cart_clear'),
    path('cart/data/',                              views.cart_data,               name='cart_data'),

    # ── Checkout ──────────────────────────────────────────────────────────────
    path('checkout/',                               views.checkout,                name='checkout'),

    # ── Orders ────────────────────────────────────────────────────────────────
    path('orders/',                                 views.order_history,           name='order_history'),
    path('order/<str:ref>/',                        views.order_track,             name='order_track'),
    path('order/<str:ref>/api/',                    views.order_track_api,         name='order_track_api'),
    path('order/<str:ref>/reorder/',                views.reorder,                 name='reorder'),

    # ── Ratings (item 9) — all in views.py ───────────────────────────────────
    path('rate/<str:order_ref>/',                   views.rate_food_order,         name='rate_order'),

    # ── Saved addresses (item 8) — all in views.py ───────────────────────────
    path('addresses/',                              views.saved_address_list,      name='addresses'),
    path('addresses/save/',                         views.saved_address_save,      name='address_save'),
    path('addresses/<int:pk>/delete/',              views.saved_address_delete,    name='address_delete'),

    # ── Payment ───────────────────────────────────────────────────────────────
    path('payment/initiate/<str:order_ref>/',       views.food_payment_initiate,   name='payment_initiate'),
    path('payment/callback/<str:tx_ref>/',          views.food_payment_callback,   name='payment_callback'),
    path('payment/webhook/',                        views.food_payment_webhook,    name='payment_webhook'),
    path('payment/status/<str:order_ref>/',         views.food_payment_status,     name='payment_status'),
    # Browser return URL after Hubtel payment (iFrame postMessage + direct return)
    path('payment/return/<str:order_ref>/',         views.food_payment_return,     name='pay_return'),
]
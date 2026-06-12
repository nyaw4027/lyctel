from django.urls import path
from . import views

app_name = 'food'

urlpatterns = [
    # Home — vendor listing
    path('',                            views.food_home,        name='home'),

    # Vendor menu
    path('restaurant/<slug:slug>/',     views.vendor_menu,      name='menu'),

    # Cart APIs
    path('cart/add/<int:item_id>/',     views.cart_add,         name='cart_add'),
    path('cart/update/<int:item_id>/',  views.cart_update,      name='cart_update'),
    path('cart/clear/',                 views.cart_clear,        name='cart_clear'),
    path('cart/data/',                  views.cart_data,         name='cart_data'),

    # Pricing API
    path('price/',                      views.price_estimate,    name='price_estimate'),

    # Checkout
    path('checkout/',                   views.checkout,          name='checkout'),

    # Order tracking
    path('order/<str:ref>/',            views.order_track,       name='order_track'),
    path('order/<str:ref>/status/',     views.order_track_api,   name='order_track_api'),

    # Order history
    path('orders/',                     views.order_history,     name='orders'),
]
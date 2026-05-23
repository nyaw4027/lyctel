# staff/urls.py
from django.urls import path
from . import views

app_name = 'staff'

urlpatterns = [
    # Dashboard
    path('',                              views.dashboard,       name='home'),

    # Orders
    path('orders/',                       views.order_list,      name='order_list'),
    path('orders/<int:pk>/',              views.order_detail,    name='order_detail'),

    # Products
    path('products/',                     views.product_list,    name='product_list'),
    path('products/<int:pk>/toggle/',     views.product_toggle,  name='product_toggle'),

    # Vendors
    path('vendors/',                      views.vendor_list,     name='vendor_list'),
    path('vendors/<int:pk>/',             views.vendor_detail,   name='vendor_detail'),

    # Riders
    path('riders/',                       views.rider_list,      name='rider_list'),
    path('riders/<int:pk>/',              views.rider_detail,    name='rider_detail'),

    # Customers
    path('customers/',                    views.customer_list,   name='customer_list'),
    path('customers/<int:pk>/',           views.customer_detail, name='customer_detail'),
]
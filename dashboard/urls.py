from django.urls import path
from . import views

app_name = 'dashboard'

urlpatterns = [
    # Overview
    path('',                              views.dashboard_home,      name='home'),

    # Products
    path('products/',                     views.product_list,        name='product_list'),
    path('products/add/',                 views.product_add,         name='product_add'),
    path('products/<int:pk>/edit/',       views.product_edit,        name='product_edit'),
    path('products/<int:pk>/delete/',     views.product_delete,      name='product_delete'),
    path('products/image/<int:pk>/delete/', views.product_image_delete, name='product_image_delete'),

    # Orders
    path('orders/',                       views.order_list,          name='order_list'),
    path('orders/<int:pk>/',              views.order_detail,        name='order_detail'),

    # Riders
    path('riders/',                       views.rider_list,          name='rider_list'),
    path('riders/<int:pk>/',              views.rider_detail,        name='rider_detail'),

    # Categories
    path('categories/',                   views.category_list,       name='category_list'),
]
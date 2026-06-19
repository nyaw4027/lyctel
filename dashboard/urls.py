from django.urls import path
from . import views

app_name = 'dashboard'

urlpatterns = [
    # Overview
    path('',                                    views.dashboard_home,         name='home'),

    # Products
    path('products/',                           views.product_list,           name='product_list'),
    path('products/add/',                       views.product_add,            name='product_add'),
    path('products/<int:pk>/edit/',             views.product_edit,           name='product_edit'),
    path('products/<int:pk>/delete/',           views.product_delete,         name='product_delete'),
    path('products/image/<int:pk>/delete/',     views.product_image_delete,   name='product_image_delete'),

    # Orders
    path('orders/',                             views.order_list,             name='order_list'),
    path('orders/<int:pk>/',                    views.order_detail,           name='order_detail'),

    # Riders
    path('riders/',                             views.rider_list,             name='rider_list'),
    path('riders/<int:pk>/',                    views.rider_detail,           name='rider_detail'),

    # Categories
    path('categories/',                         views.category_list,          name='category_list'),

    # Vendors
    path('vendors/',                            views.vendor_list,            name='vendor_list'),
    path('vendors/<int:pk>/',                   views.vendor_detail,          name='vendor_detail'),
    path('commissions/',                        views.commission_overview,    name='commissions'),

    # Staff
    path('staff/',                              views.staff_list,             name='staff_list'),
    path('staff/create/',                       views.create_staff,           name='create_staff'),
    path('staff/<int:pk>/edit/',                views.edit_staff,             name='edit_staff'),
    path('staff/<int:pk>/delete/',              views.delete_staff,           name='delete_staff'),

    # Users  ← these were missing
    path('users/',                              views.user_list,              name='user_list'),
    path('users/<int:pk>/',                     views.user_detail,            name='user_detail'),



    # Add these lines to your dashboard/urls.py urlpatterns list:

# ── Food ──────────────────────────────────────────────────
path('food/',                  views.food_vendor_list,   name='food_vendor_list'),
path('food/<int:pk>/',         views.food_vendor_detail, name='food_vendor_detail'),
path('food/orders/',           views.food_orders,        name='food_orders'),

# ── Commissions (already exists in views, just needs URL) ─
path('vendors/commissions/', views.commission_overview, name='commission_overview'),

# Add these lines to your existing dashboard/urls.py urlpatterns list:

path('team/',                  views.team_list,   name='team_list'),
path('team/add/',              views.team_add,    name='team_add'),
path('team/<int:pk>/edit/',    views.team_edit,   name='team_edit'),
path('team/<int:pk>/delete/',  views.team_delete, name='team_delete'),
path('team/<int:pk>/toggle/',  views.team_toggle, name='team_toggle'),
]
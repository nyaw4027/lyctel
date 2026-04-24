from django.urls import path
from . import views
from . import apply_views

app_name = 'vendors'

urlpatterns = [
    # Public
    path('shops/',                                     views.directory,                    name='directory'),
    path('shop/<slug:slug>/',                          views.shop_page,                    name='shop'),

    # Vendor application (with GHS 100 fee)
    path('vendor/apply/',                              apply_views.apply,                  name='apply'),
    path('vendor/apply/payment/callback/',             apply_views.apply_payment_callback, name='apply_callback'),
    path('vendor/pending/',                            apply_views.pending,                name='pending'),

    # Vendor dashboard
    path('vendor/dashboard/',                          views.dashboard,                    name='dashboard'),
    path('vendor/dashboard/earnings/',                 views.earnings,                     name='earnings'),
    path('vendor/dashboard/settings/',                 views.settings_update,              name='settings'),

    # Vendor product management
    path('vendor/dashboard/products/add/',             views.product_add,                  name='product_add'),
    path('vendor/dashboard/products/<int:pk>/edit/',   views.product_edit,                 name='product_edit'),
    path('vendor/dashboard/products/<int:pk>/delete/', views.product_delete,               name='product_delete'),
]
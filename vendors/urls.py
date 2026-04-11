from django.urls import path
from . import views

app_name = 'vendors'

urlpatterns = [
    path('vendor/apply/',                    views.apply,          name='apply'),
    path('vendor/pending/',                  views.pending,        name='pending'),
    path('vendor/dashboard/',               views.dashboard,      name='dashboard'),
    path('vendor/dashboard/earnings/',      views.earnings,       name='earnings'),
    path('vendor/dashboard/products/add/',  views.product_add,    name='product_add'),
    path('vendor/dashboard/products/<int:pk>/edit/',   views.product_edit,   name='product_edit'),
    path('vendor/dashboard/products/<int:pk>/delete/', views.product_delete, name='product_delete'),
    path('shop/<slug:slug>/',               views.shop_page,      name='shop'),
]
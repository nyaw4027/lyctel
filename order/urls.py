from django.urls import path
from . import views

app_name = 'order'

urlpatterns = [
    path('checkout/',                        views.checkout,           name='checkout'),
    path('',                                 views.order_history,      name='history'),
    path('<str:order_ref>/confirm/',         views.order_confirmation, name='confirmation'),
    path('<str:order_ref>/track/',           views.order_tracking,     name='tracking'),
   # path('api/list/', views.api_order_history, name='api_order_history'),
]
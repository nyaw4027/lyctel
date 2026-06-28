from django.urls import path
from . import views

app_name = 'order'

urlpatterns = [
    path('checkout/',                          views.checkout,               name='checkout'),
    path('',                                   views.order_history,          name='history'),
    path('<str:order_ref>/confirm/',           views.order_confirmation,     name='confirmation'),
    path('<str:order_ref>/track/',             views.order_tracking,         name='tracking'),
    path('confirm-pickup/<str:order_ref>/',    views.vendor_confirm_pickup,  name='confirm_pickup'),
    path('dispatch-parcel/<str:order_ref>/',   views.vendor_dispatch_parcel, name='dispatch_parcel'),
    path('estimate-fee/', views.estimate_delivery_fee, name='estimate_fee'),
]
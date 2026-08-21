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
    path('estimate-fee/',                      views.estimate_delivery_fee,  name='estimate_fee'),
    path('orders/<str:order_ref>/receipt/',    views.order_receipt,          name='receipt'),

    # Smart reorder
    path('<str:order_ref>/reorder/',           views.reorder,                name='reorder'),

    # Also bought (AJAX)
    path('also-bought/<int:product_id>/',      views.also_bought,            name='also_bought'),

    # Disputes
    path('<str:order_ref>/dispute/',           views.open_dispute,           name='open_dispute'),
    path('<str:order_ref>/dispute/detail/',    views.dispute_detail,         name='dispute_detail'),
    path('disputes/<uuid:dispute_id>/vendor-respond/',
                                               views.vendor_respond_dispute, name='vendor_respond_dispute'),
    path('disputes/',                          views.staff_dispute_list,     name='staff_disputes'),
    path('disputes/<uuid:dispute_id>/resolve/',
                                               views.staff_resolve_dispute,  name='staff_resolve_dispute'),
]
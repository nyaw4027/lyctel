from django.urls import path
from . import views

app_name = 'rider'

urlpatterns = [
    # Apply to become a rider
    path('apply/',                          views.apply,                name='apply'),
    path('pending/',                        views.pending,              name='pending'),

    # Dashboard
    path('',                                views.dashboard,            name='dashboard'),
    path('toggle/',                         views.toggle_status,        name='toggle_status'),

    # Delivery actions
    path('accept/<int:pk>/',               views.accept_delivery,      name='accept_delivery'),
    path('reject/<int:pk>/',               views.reject_delivery,      name='reject_delivery'),
    path('map/<int:pk>/',                  views.live_map,             name='live_map'),
    path('delivery/<int:pk>/update/',      views.update_delivery,      name='update_delivery'),

    # Location
    path('location/update/',               views.update_location,      name='update_location'),
    path('location/<str:order_ref>/',      views.location_api,         name='location_api'),
    path('eta/',                           views.eta_api,              name='eta_api'),

    # Notifications
    path('notifications/<int:pk>/read/',   views.notif_read,           name='notif_read'),
    path('notifications/read-all/',        views.notif_read_all,       name='notif_read_all'),
    path('notifications/count/',           views.notif_count,          name='notif_count'),

    # Earnings
    path('earnings/',                      views.earnings,             name='earnings'),
    # Commission ledger & balances
    path('balance/',                          views.my_balance,           name='my_balance'),
    path('admin/balances/',                   views.admin_balances,       name='admin_balances'),
    path('admin/balances/<int:rider_pk>/',    views.rider_ledger_detail,  name='ledger_detail'),
    path('admin/balances/<int:rider_pk>/settle/', views.settle_rider_balance, name='settle_balance'),
]
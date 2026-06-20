# chat/urls.py
from django.urls import path
from . import views

app_name = 'chat'

urlpatterns = [
    # Vendor chat
    path('',                          views.inbox,              name='inbox'),
    path('<uuid:room_id>/',           views.room,                name='room'),
    path('start/<slug:vendor_slug>/', views.start_chat,          name='start'),
    path('unread/',                   views.unread_count,        name='unread_count'),

    # Support chat
    path('support/start/',                  views.support_start,        name='support_start'),
    path('support/<uuid:room_id>/',         views.support_room,         name='support_room'),
    path('support/<uuid:room_id>/resolve/', views.support_resolve,      name='support_resolve'),
    path('support/inbox/mine/',             views.support_my_inbox,     name='support_my_inbox'),
    path('support/inbox/admin/',            views.support_admin_inbox,  name='support_admin_inbox'),

    # Attachments (shared)
    path('upload/<str:room_type>/<uuid:room_id>/', views.upload_attachment, name='upload_attachment'),
]